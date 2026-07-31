TOOLS = [
    {
        "tool": "crm",
        "operation": "read_customer",
        "description": "Read customer details from CRM.",
        "parameters": {
            "customer_id": "string"
        }
    },
    {
        "tool": "crm",
        "operation": "write_customer",
        "description": "Update customer details.",
        "parameters": {
            "customer_id": "string",
            "changes": {
                "name": "string",
                "email": "string",
                "support_tier": "string",
                "address": "string"
            }
        }
    },
    {
        "tool": "crm",
        "operation": "delete_customer",
        "description": "Delete a customer.",
        "parameters": {
            "customer_id": "string"
        }
    }
]