# Agent #01: AI Engineering Expert
def configure_llm_parameters(task_type: str) -> dict:
    return {"temperature": 0.0 if task_type == "analytical" else 0.5}
