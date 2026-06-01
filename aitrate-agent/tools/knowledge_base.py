"""Knowledge base lookup tools — query parameter classes, filter info, strategy specs.

These tools query the vector store and return structured data.
They are thin wrappers around the retrieval layer.

NO framework imports. Pure Python + Pydantic.
"""

import structlog

from retrieval.vector_store import VectorStore
from tools.schemas import (
    FilterInfoRequest,
    FilterInfoResponse,
    ParameterClass,
    ParameterClassRequest,
    ParameterClassResponse,
    StrategySpecRequest,
    StrategySpecResponse,
)

logger = structlog.get_logger(__name__)


async def lookup_filter_info(
    request: FilterInfoRequest,
    vector_store: VectorStore,
) -> FilterInfoResponse:
    """Look up filter information from the knowledge base.

    Args:
        request: Filter lookup request.
        vector_store: Vector store instance for retrieval.

    Returns:
        Filter information with citation.
    """
    logger.info("looking_up_filter", filter_id=request.filter_id, strategy=request.strategy)

    # Build query
    query = f"Filter {request.filter_id}"
    if request.strategy:
        query += f" in {request.strategy}"
    query += " — what does it do, what are its parameters, what class is it"

    # Retrieve from KB
    results = await vector_store.search(
        query=query,
        top_k=5,
        filter_doc_type="filter_glossary",
    )

    if not results:
        # Try broader search
        results = await vector_store.search(query=query, top_k=5)

    if not results:
        raise ValueError(
            f"No information found for filter {request.filter_id}. "
            "The filter glossary may not be ingested yet."
        )

    # Use top result
    top = results[0]

    return FilterInfoResponse(
        filter_id=request.filter_id,
        name=top.metadata.get("filter_name", request.filter_id),
        description=top.content,
        strategy=top.metadata.get("strategy", request.strategy or "Unknown"),
        class_=top.metadata.get("class"),
        citation=top.citation_handle,
        source_doc=top.source_file,
        line_number=top.line_number,
    )


async def lookup_parameter_class(
    request: ParameterClassRequest,
    vector_store: VectorStore,
) -> ParameterClassResponse:
    """Look up parameter class (A/B/C) from the knowledge base.

    Args:
        request: Parameter class lookup request.
        vector_store: Vector store instance for retrieval.

    Returns:
        Parameter class information with citation.
    """
    logger.info(
        "looking_up_parameter_class",
        parameter=request.parameter_name,
        strategy=request.strategy,
    )

    query = f"Parameter {request.parameter_name} class A B C"
    if request.strategy:
        query += f" in {request.strategy}"

    results = await vector_store.search(
        query=query,
        top_k=5,
        filter_doc_type="parameter_class",
    )

    if not results:
        results = await vector_store.search(query=query, top_k=5)

    if not results:
        raise ValueError(
            f"No class information found for parameter {request.parameter_name}. "
            "The parameter class master may not be ingested yet."
        )

    top = results[0]

    # Parse class from metadata or content
    class_str = top.metadata.get("class", "B")
    try:
        param_class = ParameterClass(class_str)
    except ValueError:
        param_class = ParameterClass.B

    return ParameterClassResponse(
        parameter_name=request.parameter_name,
        class_=param_class,
        baseline=top.metadata.get("baseline"),
        range_min=top.metadata.get("range_min"),
        range_max=top.metadata.get("range_max"),
        rationale=top.content,
        citation=top.citation_handle,
        source_doc=top.source_file,
    )


async def lookup_strategy_spec(
    request: StrategySpecRequest,
    vector_store: VectorStore,
) -> StrategySpecResponse:
    """Look up strategy specification from the knowledge base.

    Args:
        request: Strategy spec lookup request.
        vector_store: Vector store instance for retrieval.

    Returns:
        Strategy specification with citation.
    """
    logger.info("looking_up_strategy", strategy=request.strategy_name, aspect=request.aspect)

    query = f"{request.strategy_name} strategy specification"
    if request.aspect:
        query += f" {request.aspect}"

    results = await vector_store.search(
        query=query,
        top_k=10,
        filter_doc_type="strategy_spec",
    )

    if not results:
        results = await vector_store.search(query=query, top_k=10)

    if not results:
        raise ValueError(
            f"No specification found for strategy {request.strategy_name}. "
            "The strategy spec may not be ingested yet."
        )

    # Combine top results for comprehensive answer
    combined_content = "\n\n".join(r.content for r in results[:3])
    top = results[0]

    return StrategySpecResponse(
        strategy_name=request.strategy_name,
        architecture=top.metadata.get("architecture", "Unknown"),
        description=combined_content,
        filters=top.metadata.get("filters", []),
        exit_mechanisms=top.metadata.get("exit_mechanisms", []),
        parameters_count=top.metadata.get("parameters_count", 0),
        citation=top.citation_handle,
        source_doc=top.source_file,
    )
