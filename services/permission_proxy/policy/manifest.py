from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StringConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["string"]
    max_length: int | None = Field(default=None, alias="maxLength", ge=1, le=4096)


class ObjectConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["object"]


PropertyConstraint = Annotated[
    StringConstraint | ObjectConstraint,
    Field(discriminator="type"),
]


class ParameterSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    required: list[str] = Field(default_factory=list)
    properties: dict[str, PropertyConstraint]
    additional_properties: bool = Field(default=False, alias="additionalProperties")

    @model_validator(mode="after")
    def required_fields_must_be_declared(self) -> "ParameterSchema":
        unknown = set(self.required) - set(self.properties)
        if unknown:
            raise ValueError(f"Required parameters are not declared: {sorted(unknown)}")
        return self


class SessionParameterRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["session_value_equals_parameter"]
    session_claim: Literal["customer_id", "user_id"]
    parameter: str = Field(min_length=1, max_length=100)


class DataScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all: list[SessionParameterRule] = Field(min_length=1)


class OperationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter_schema: ParameterSchema
    data_scope: DataScope | None = None


class ToolPermission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_operations: list[str] = Field(min_length=1)
    operation_rules: dict[str, OperationRule]

    @model_validator(mode="after")
    def allowed_operations_must_have_rules(self) -> "ToolPermission":
        missing = set(self.allowed_operations) - set(self.operation_rules)
        if missing:
            raise ValueError(f"Allowed operations are missing rules: {sorted(missing)}")
        unknown = set(self.operation_rules) - set(self.allowed_operations)
        if unknown:
            raise ValueError(f"Rules exist for non-allowed operations: {sorted(unknown)}")
        return self


class ManifestDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    manifest_id: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=64)
    tools: dict[str, ToolPermission] = Field(min_length=1)
    deny_message: str = Field(min_length=1, max_length=500)


def validate_parameters(schema: ParameterSchema, parameters: dict[str, Any]) -> bool:
    if any(required not in parameters for required in schema.required):
        return False
    if not schema.additional_properties and set(parameters) - set(schema.properties):
        return False

    for name, value in parameters.items():
        constraint = schema.properties.get(name)
        if constraint is None:
            continue
        if isinstance(constraint, StringConstraint):
            if not isinstance(value, str):
                return False
            if constraint.max_length is not None and len(value) > constraint.max_length:
                return False
        elif isinstance(constraint, ObjectConstraint) and not isinstance(value, dict):
            return False
    return True
