from dotenv import load_dotenv
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from retriever import NotesRetriever
from vector_store import VectorStore

load_dotenv()

GROQ_MODEL = "openai/gpt-oss-120b"


class RAGAnswer(BaseModel):
    answer: str = Field(
        description="The answer to the user's question, based only on the provided context."
    )
    sources: list[str] = Field(
        description=(
            "The exact source labels (e.g. 'notes\\README.md #0') of the context "
            "chunks actually used to build the answer. Empty list if the answer "
            "is 'I don't know'."
        )
    )


SYSTEM_PROMPT = (
    "You are a personal knowledge base assistant. Answer the user's question "
    "using ONLY the context below, drawn from the user's own notes. "
    "If the context doesn't contain the answer, say you don't know instead of guessing. "
    "Each context chunk is labeled like '[source #index]' — copy the exact label(s) "
    "of the chunk(s) you actually used into the sources field.\n\n"
    "Context:\n{context}"
)

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ]
)

llm = ChatGroq(model=GROQ_MODEL, temperature=0)
structured_llm = llm.with_structured_output(RAGAnswer)

CONDENSE_SYSTEM_PROMPT = (
    "Given the conversation history and a follow-up question, rewrite the "
    "follow-up into a standalone question that can be understood without the "
    "history. Do not answer it — only rewrite it. If it's already standalone, "
    "return it unchanged, with no extra commentary."
)

condense_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", CONDENSE_SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ]
)

condense_question_chain = condense_prompt | llm


def _standalone_question(x: dict) -> str:
    # First turn (or no history yet): nothing to rewrite, use the question as-is.
    if not x.get("history"):
        return x["question"]
    rewritten = condense_question_chain.invoke(
        {"question": x["question"], "history": x["history"]}
    )
    return rewritten.content


def format_docs(docs: list[Document]) -> str:
    parts = [
        f"[{doc.metadata['source']} #{doc.metadata['chunk_index']}]\n{doc.page_content}"
        for doc in docs
    ]
    return "\n\n".join(parts)


def _to_history_compatible_output(result: RAGAnswer) -> dict:
    # RunnableWithMessageHistory needs *something* it recognizes as "the AI's
    # message" to append to the conversation history. Our chain's real output
    # (RAGAnswer) isn't a string or a message, so we hand it a plain AIMessage
    # built from the answer text (via history_message), while still returning
    # the full structured result (answer + sources) for our own use.
    return {
        "answer": result.answer,
        "sources": result.sources,
        "history_message": AIMessage(content=result.answer),
    }


def build_chain(retriever: NotesRetriever):
    return (
        RunnablePassthrough.assign(
            context=lambda x: format_docs(retriever.invoke(_standalone_question(x)))
        )
        | prompt
        | structured_llm
        | RunnableLambda(_to_history_compatible_output)
    )


_session_store: dict[str, InMemoryChatMessageHistory] = {}


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in _session_store:
        _session_store[session_id] = InMemoryChatMessageHistory()
    return _session_store[session_id]


def build_conversational_chain(retriever: NotesRetriever):
    return RunnableWithMessageHistory(
        build_chain(retriever),
        get_session_history,
        input_messages_key="question",
        history_messages_key="history",
        output_messages_key="history_message",
    )


if __name__ == "__main__":
    store = VectorStore()
    store.load("index")
    retriever = NotesRetriever(store=store, top_k=3)
    conversational_chain = build_conversational_chain(retriever)
    config = {"configurable": {"session_id": "cli-test"}}

    for question in ["What does Ritvik do?", "What tools does he use for that?"]:
        result = conversational_chain.invoke({"question": question}, config=config)
        print(f"Question: {question}")
        print(f"Answer: {result['answer']}")
        sources = result["sources"]
        print(f"Sources: {', '.join(sources) if sources else 'none'}\n")
