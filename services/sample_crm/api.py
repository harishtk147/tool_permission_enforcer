import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from services.common.database import Database
from services.common.settings import SampleCRMSettings
from services.sample_crm.domain.models import CRMCustomer
from services.sample_crm.persistence.repositories import CustomerRepository


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    name: str
    email: str
    support_tier: str
    address: str


class CustomerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    support_tier: str | None = Field(default=None, min_length=1, max_length=50)
    address: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_change(self) -> "CustomerPatch":
        if not self.model_fields_set:
            raise ValueError("At least one customer field must be supplied")
        return self


def build_customer_router(*, database: Database, settings: SampleCRMSettings) -> APIRouter:
    router = APIRouter(prefix="/customers", tags=["customers"])

    def require_internal_key(
        supplied_key: Annotated[str | None, Header(alias="X-Internal-API-Key")] = None,
    ) -> None:
        expected = settings.internal_api_key.get_secret_value()
        if supplied_key is None or not hmac.compare_digest(supplied_key, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_INTERNAL_CREDENTIAL"},
            )

    InternalCredential = Annotated[None, Depends(require_internal_key)]

    @router.get("/{customer_id}", response_model=CustomerResponse)
    def read_customer(customer_id: str, _: InternalCredential) -> CRMCustomer:
        with database.session() as session:
            customer = CustomerRepository(session).get(customer_id)
            if customer is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "CUSTOMER_NOT_FOUND"},
                )
            return customer

    @router.patch("/{customer_id}", response_model=CustomerResponse)
    def update_customer(
        customer_id: str,
        changes: CustomerPatch,
        _: InternalCredential,
    ) -> CRMCustomer:
        with database.session() as session:
            customer = CustomerRepository(session).get(customer_id)
            if customer is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "CUSTOMER_NOT_FOUND"},
                )
            for field, value in changes.model_dump(exclude_unset=True).items():
                setattr(customer, field, value)
            session.flush()
            return customer

    @router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_customer(customer_id: str, _: InternalCredential) -> Response:
        with database.session() as session:
            repository = CustomerRepository(session)
            customer = repository.get(customer_id)
            if customer is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "CUSTOMER_NOT_FOUND"},
                )
            repository.delete(customer)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
