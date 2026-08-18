from src.processors.zoho_crm_processor import ZohoCRMProcessor, slugify

FIELDS = {
    "fields": {
        "id": "id",
        "name": "Product_Name",
        "text": "Description",
        "category": "Product_Category",
        "url": "Website",
        "active": "Active",
        "price": "Unit_Price",
        "product_code": "Product_Code",
    },
    "filter": {"active_only": True},
}


def _record(**overrides):
    record = {
        "id": "1001",
        "Product_Name": "Somesa Education Plan",
        "Description": "A flexible savings plan for education.",
        "Product_Category": "Savings",
        "Website": "https://www.oldmutual.co.ug/somesa",
        "Active": True,
        "Unit_Price": "150000",
        "Product_Code": "SOM-1",
    }
    record.update(overrides)
    return record


def test_slugify():
    assert slugify("Somesa Education Plan") == "somesa-education-plan"
    assert slugify("  Travel  Sure  Plus  ") == "travel-sure-plus"
    assert slugify("M-PESA++Premiums") == "m-pesa-premiums"


def test_record_produces_website_chunk_schema():
    chunk = ZohoCRMProcessor(FIELDS).process_record(_record())

    assert chunk is not None
    assert chunk["doc_id"] == "zoho:product:somesa-education-plan"
    assert chunk["id"] == "zoho:product:somesa-education-plan:catalogue:chunk:0.0"
    assert chunk["type"] == "product"
    assert chunk["title"] == "Somesa Education Plan"
    assert chunk["chunk_type"] == "catalogue"
    assert chunk["url"] == "https://www.oldmutual.co.ug/somesa"
    assert "flexible savings plan" in chunk["text"]
    assert "Price: 150000" in chunk["text"]
    assert chunk["zoho_record_id"] == "1001"


def test_inactive_record_skipped():
    processor = ZohoCRMProcessor(FIELDS)
    assert processor.process_record(_record(Active=False)) is None
    assert processor.process_record(_record(Active="false")) is None
    assert processor.process_record(_record(Active=True)) is not None


def test_empty_name_skipped():
    assert ZohoCRMProcessor(FIELDS).process_record(_record(Product_Name="")) is None


def test_attach_to_existing_product_by_title():
    existing_index = {
        "website:product:personal/save-and-invest/somesa-education-plan": {
            "type": "product",
            "title": "Somesa Education Plan",
            "category": "personal",
            "subcategory": "save-and-invest",
        }
    }
    chunk = ZohoCRMProcessor(FIELDS, existing_index=existing_index).process_record(_record())

    assert chunk["attached_product_doc_id"] == "website:product:personal/save-and-invest/somesa-education-plan"
    assert chunk["category"] == "personal"
    assert chunk["subcategory"] == "save-and-invest"


def test_unmatched_record_falls_back_to_category_config():
    chunk = ZohoCRMProcessor(FIELDS).process_record(_record(Product_Category=""))

    assert chunk["category"] == "general"
    assert chunk["subcategory"] == "products"


def test_process_returns_chunks_and_index_entries():
    chunks, index = ZohoCRMProcessor(FIELDS).process([_record(id="1001"), _record(id="2", Product_Name="")])

    assert len(chunks) == 1
    doc_id = chunks[0]["doc_id"]
    entry = index[doc_id]
    assert entry["type"] == "product"
    assert entry["product_key"] == "somesa-education-plan"
    assert entry["chunk_ids"] == [chunks[0]["id"]]
    assert entry["zoho_record_id"] == "1001"


def test_price_omitted_when_disabled():
    config = dict(FIELDS)
    config["include_price_in_text"] = False
    chunk = ZohoCRMProcessor(config).process_record(_record())

    assert "Price:" not in chunk["text"]
