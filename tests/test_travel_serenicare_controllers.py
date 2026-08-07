import pytest

from src.database.postgres import PostgresDB
from src.chatbot.controllers.travel_insurance_controller import TravelInsuranceController
from src.chatbot.controllers.serenicare_controller import SerenicareController


@pytest.fixture
def db():
    return PostgresDB()


def test_travel_application_lifecycle(db):
    ctrl = TravelInsuranceController(db)
    app = ctrl.create_application("user1", {})
    assert app["user_id"] == "user1"
    app_id = app["id"]

    # update product
    updated = ctrl.update_product_selection(app_id, {"product_id": "worldwide_essential"})
    assert updated["selected_product"]["id"] == "worldwide_essential"

    # about you
    updated = ctrl.update_about_you(app_id, {"first_name": "Jane", "surname": "Doe"})
    assert updated["about_you"]["first_name"] == "Jane"

    # travellers
    updated = ctrl.update_traveller_details(app_id, {"first_name": "Jane", "surname": "Doe"})
    assert len(updated["travellers"]) >= 1

    # finalize
    pricing = {"total_ugx": 1000, "breakdown": {}}
    finalized = ctrl.finalize_and_create_quote(app_id, "user1", pricing)
    assert finalized["quote_id"] is not None

    # cleanup
    assert ctrl.delete_application(app_id) is True


def test_serenicare_application_lifecycle(db):

    def test_serenicare_full_form_validation(db):
        from src.chatbot.flows.serenicare import SerenicareFlow
        ctrl = SerenicareController(db)
        flow = SerenicareFlow(None, db)
        app = ctrl.create_application("user3", {})
        app_id = app["id"]

        # Valid payload
        payload = {
            "firstName": "John",
            "lastName": "Doe",
            "middleName": "Middle",
            "mobile": "+256712345678",
            "email": "john.doe@example.com",
            "planType": "classic",
            "optionalBenefits": ["outpatient", "dental"],
            "seriousConditions": "no",
            "mainMembers": [
                {
                    "includeSpouse": False,
                    "includeChildren": False,
                    "dob": "1990-01-01",
                    "age": 36
                },
                {
                    "includeSpouse": True,
                    "includeChildren": False,
                    "dob": "1990-01-01",
                    "age": 36
                },
            ]
        }
        result = flow.process_serenicare_form(app_id, payload)
        assert result["first_name"] == "John"
        assert result["plan_type"] == "classic"
        assert result["main_members"][0]["dob"] == "1990-01-01"

        # Invalid payload (missing required, bad values)
        bad_payload = {
            "firstName": "J",
            "lastName": "",
            "mobile": "123",
            "email": "bademail",
            "planType": "invalid",
            "optionalBenefits": ["invalid"],
            "seriousConditions": "maybe",
            "mainMembers": [
                {
                    "includeSpouse": True,
                    "includeChildren": True,
                    "dob": "2027-01-01",
                    "age": 5
                }
            ]
        }
        import pytest
        with pytest.raises(Exception):
            flow.process_serenicare_form(app_id, bad_payload)
    ctrl = SerenicareController(db)
    app = ctrl.create_application("user2", {})
    app_id = app["id"]

    updated = ctrl.update_cover_personalization(
        app_id,
        {
            "date_of_birth": "1990-01-01",
            "include_spouse": True,
            "spouse_dob": "1992-01-01",
            "include_children": True,
            "child_dob": "2016-04-10",
            "add_another_main_member": True,
            "other_member_dob": "1987-09-20",
        },
    )
    assert updated["cover_personalization"]["date_of_birth"] == "1990-01-01"
    assert updated["cover_personalization"]["spouse_dob"] == "1992-01-01"
    assert updated["cover_personalization"]["child_dob"] == "2016-04-10"
    assert updated["cover_personalization"]["other_member_dob"] == "1987-09-20"

    updated = ctrl.update_optional_benefits(app_id, {"optional_benefits": "outpatient,maternity"})
    assert "outpatient" in updated["optional_benefits"]

    updated = ctrl.update_plan_selection(app_id, {"plan_option": "classic"})
    assert updated["plan_option"]["id"] == "classic"

    pricing = {"monthly": 500.0, "breakdown": {}}
    finalized = ctrl.finalize_and_create_quote(app_id, "user2", pricing)
    assert finalized["quote_id"] is not None

    assert ctrl.delete_application(app_id) is True
