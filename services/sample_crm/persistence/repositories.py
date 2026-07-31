from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.sample_crm.domain.models import CRMCustomer


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, customer_id: str) -> CRMCustomer | None:
        return self.session.get(CRMCustomer, customer_id)

    def add(self, customer: CRMCustomer) -> CRMCustomer:
        self.session.add(customer)
        self.session.flush()
        return customer

    def delete(self, customer: CRMCustomer) -> None:
        self.session.delete(customer)
        self.session.flush()

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(CRMCustomer)) or 0
