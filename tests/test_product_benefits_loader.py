from src.integrations.product_benefits import product_benefits_loader


def test_motor_private_benefits_not_empty_from_repo_config():
    benefits = product_benefits_loader.get_benefits_as_dict("motor_private", 0)

    assert isinstance(benefits, list)
    assert len(benefits) > 0
    assert all("label" in item and "value" in item for item in benefits)
