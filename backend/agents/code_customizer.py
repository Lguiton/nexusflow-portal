# Agent #02: Software Engineer Agent
def generate_dynamic_model(field_name: str) -> str:
    return f"class Dynamic{field_name.capitalize()}(BaseModel): value: Any"
