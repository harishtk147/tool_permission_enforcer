import pytest
from pydantic import ValidationError

from services.permission_proxy.persistence.seed import READ_ONLY_MANIFEST
from services.permission_proxy.policy.manifest import ManifestDocument, validate_parameters


def test_seed_manifest_is_strictly_typed() -> None:
    manifest = ManifestDocument.model_validate(READ_ONLY_MANIFEST)
    schema = manifest.tools["crm"].operation_rules["read_customer"].parameter_schema

    assert validate_parameters(schema, {"customer_id": "customer_1001"}) is True
    assert validate_parameters(schema, {}) is False
    assert validate_parameters(schema, {"customer_id": 1001}) is False
    assert (
        validate_parameters(
            schema,
            {"customer_id": "customer_1001", "destination_url": "http://attacker"},
        )
        is False
    )


def test_manifest_rejects_unknown_fields_and_rule_types() -> None:
    document = {
        **READ_ONLY_MANIFEST,
        "execute_python": "print('unsafe')",
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ManifestDocument.model_validate(document)

    document = {
        **READ_ONLY_MANIFEST,
        "tools": {
            "crm": {
                "allowed_operations": ["read_customer"],
                "operation_rules": {
                    "read_customer": {
                        "parameter_schema": {
                            "required": ["customer_id"],
                            "properties": {"customer_id": {"type": "string"}},
                        },
                        "data_scope": {
                            "all": [
                                {
                                    "type": "execute_expression",
                                    "session_claim": "customer_id",
                                    "parameter": "customer_id",
                                }
                            ]
                        },
                    }
                },
            }
        },
    }
    with pytest.raises(ValidationError):
        ManifestDocument.model_validate(document)
