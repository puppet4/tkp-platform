from tkp_api.utils.masking import default_masker


def test_default_masker_masks_sensitive_fields_recursively():
    payload = {
        "token": "abcd1234efgh",
        "profile": {
            "email": "alice@example.com",
            "items": [{"password": "s3cr3t"}],
        },
        "message": "hello world",
    }

    masked = default_masker.mask_dict(payload, recursive=True)

    assert masked["token"] != payload["token"]
    assert masked["profile"]["email"] != payload["profile"]["email"]
    assert masked["profile"]["items"][0]["password"] != payload["profile"]["items"][0]["password"]
    assert masked["message"] == payload["message"]


def test_default_masker_non_recursive_only_masks_top_level():
    payload = {
        "api_key": "xyz123456",
        "nested": {"token": "inner-token"},
    }

    masked = default_masker.mask_dict(payload, recursive=False)

    assert masked["api_key"] != payload["api_key"]
    assert masked["nested"] == payload["nested"]
