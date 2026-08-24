import json
import logging
import os
from typing import Any, Dict, List, Union

from dotenv import load_dotenv
from openai import OpenAI

try:
    from backend.db_manager import log_ai_usage_sync
    from backend.model_registry import get_model
except ImportError:
    from db_manager import log_ai_usage_sync
    from model_registry import get_model

env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)
logger = logging.getLogger("nexusflow.external_telemetry_scout")

# AI-03: previously no explicit request timeout at all. max_retries matches
# the openai SDK's own default (2), made explicit here rather than left
# implicit.
AI_REQUEST_TIMEOUT_SECONDS = 30.0
AI_MAX_RETRIES = 2

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=AI_MAX_RETRIES) if api_key else None
 
 
def _flatten_json(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """
    Deterministically flattens an arbitrary JSON structure into a flat
    {column_name: sample_value} mapping -- real recursive computation, not
    an LLM guess. Nested objects join keys with '_'. Lists are represented
    as a single column holding the JSON-encoded array (a safe default for
    heterogeneous/variable-length arrays, rather than guessing an expansion
    that may not hold for every record).
    """
    flat: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            safe_key = "".join(c if (c.isalnum() or c == "_") else "_" for c in str(key))
            new_prefix = f"{prefix}_{safe_key}" if prefix else safe_key
            if isinstance(value, dict):
                flat.update(_flatten_json(value, new_prefix))
            elif isinstance(value, list):
                flat[new_prefix] = json.dumps(value)
            else:
                flat[new_prefix] = value
    else:
        flat[prefix or "value"] = obj
    return flat
 
 
def _infer_duckdb_type(value: Any) -> str:
    # bool check must precede int -- in Python, bool is a subclass of int,
    # so isinstance(True, int) is also True and would otherwise misclassify
    # every boolean sample as BIGINT.
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "BIGINT"
    if isinstance(value, float):
        return "DOUBLE"
    return "VARCHAR"  # covers str, None (unknown from a single null sample), and anything else
 
 
def _summarize_with_llm(client_id: str, query: str, schema_mapping: Dict[str, str], sample_row: Dict[str, Any]) -> List[str]:
    """
    Optional commentary layer only. Unlike the previous version of this
    agent, the schema mapping below is already a real, verified fact by the
    time this runs -- the model is asked to comment on it (schema
    stability, naming, follow-up questions), never to invent it.
    """
    if not client:
        return ["OpenAI client not configured -- no narrative commentary available; the schema mapping above was derived directly from the real sample payload regardless."]
    safe_client_id = "".join(c for c in client_id if c.isalnum() or c in "-_")
    system_prompt = f"""
    You are the External Telemetry Scout. Client: {safe_client_id}.
    A real sample payload was already flattened into this verified DuckDB
    schema mapping: {json.dumps(schema_mapping)}
    Sample flattened row: {json.dumps(sample_row, default=str)}
    Original request: {query}
    Provide up to 3 short, practical observations about this schema
    (naming clarity, likely type-inference edge cases, follow-up questions
    to ask before creating a table from it) -- do not invent a different
    schema or claim to have fetched anything yourself.
    Respond STRICTLY in JSON: {{"insights": ["..."]}}
    """
    try:
        model = get_model("external_telemetry_scout")
        res = client.chat.completions.create(
            model=model, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system_prompt}], temperature=0.3
        )
        usage = getattr(res, "usage", None)
        if usage:
            log_ai_usage_sync(
                safe_client_id, "external_telemetry_scout", model,
                getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0), getattr(usage, "total_tokens", 0),
                "SUCCESS"
            )
        parsed = json.loads(res.choices[0].message.content)
        insights = parsed.get("insights")
        if isinstance(insights, list):
            return [str(i) for i in insights]
        return []
    except Exception as e:
        logger.warning(f"Telemetry Scout commentary generation failed (non-fatal, schema mapping above is unaffected): {e}")
        return []
 
 
def execute_task(client_id: str = "default_client", query: str = "", sample_payload: Union[str, dict, list, None] = None) -> Dict[str, Any]:
    """
    Real external-telemetry schema mapping: given a sample JSON payload
    (pasted or uploaded -- this function makes no outbound network calls of
    its own), deterministically flattens and infers a real DuckDB schema
    mapping from it. No invented endpoints, no invented schemas. Does NOT
    create/alter any DuckDB table itself -- returns the proposed mapping
    and a data sample for review before any schema change is applied.
    """
    if sample_payload is None or sample_payload == "":
        return {
            "agent": "External Telemetry Scout",
            "status": "ERROR",
            "insights": ["No sample_payload was provided -- paste or upload a representative JSON sample from the external source to map."]
        }
 
    if isinstance(sample_payload, (dict, list)):
        payload = sample_payload
    else:
        try:
            payload = json.loads(sample_payload)
        except json.JSONDecodeError as e:
            logger.warning(f"Telemetry Scout received malformed sample payload for {client_id}: {e}")
            return {
                "agent": "External Telemetry Scout",
                "status": "ERROR",
                "insights": [f"sample_payload is not valid JSON: {e}"]
            }
 
    # A top-level JSON array is common for list-shaped exports -- flatten
    # using the first element as the representative shape (a genuinely
    # empty array has nothing to infer a schema from, so that's reported
    # as an error rather than silently returning an empty mapping).
    if isinstance(payload, list):
        if not payload:
            return {
                "agent": "External Telemetry Scout",
                "status": "ERROR",
                "insights": ["sample_payload is an empty JSON array -- nothing to infer a schema from."]
            }
        sample_record = payload[0]
    else:
        sample_record = payload
 
    try:
        flat_sample = _flatten_json(sample_record)
    except Exception as e:
        logger.error(f"Telemetry Scout flattening failed for {client_id}: {e}")
        return {"agent": "External Telemetry Scout", "status": "ERROR", "insights": [f"Failed to flatten sample_payload: {e}"]}
 
    schema_mapping = {col: _infer_duckdb_type(val) for col, val in flat_sample.items()}
    insights = _summarize_with_llm(client_id, query, schema_mapping, flat_sample)
 
    return {
        "agent": "External Telemetry Scout",
        "status": "COMPLETED",
        "duckdb_schema_mapping": schema_mapping,
        "sample_row": flat_sample,
        "insights": insights or ["Schema mapping derived directly from the real sample payload provided."]
    }