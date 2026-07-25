from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import canonical_json, dedupe_keep_order, prepare_payload, valid_public_url
from build_sites import _filter_items, _pin_and_limit
from validate import validate_source_payload


def main() -> int:
    assert valid_public_url("https://example.com/a")
    assert not valid_public_url("file:///Users/test/a")
    assert [x["id"] for x in dedupe_keep_order([{"id": "a"}, {"id": "a"}, {"id": "b"}])] == ["a", "b"]

    old = {"schema_version": "1.0", "source": {"id": "s", "type": "note_account"}, "items": [{"id": "a", "title": "A", "url": "https://example.com/a"}], "generated_at": "old"}
    new = {"schema_version": "1.0", "source": {"id": "s", "type": "note_account"}, "items": [{"id": "a", "title": "A", "url": "https://example.com/a"}]}
    prepared, changed = prepare_payload(new, old)
    assert changed is False
    assert prepared["generated_at"] == "old"
    assert canonical_json(prepared) == canonical_json(old)
    assert not validate_source_payload(prepared)

    payloads = [{"source": {"id": "s"}, "items": [
        {"id": "1", "title": "AIの話", "url": "https://example.com/1"},
        {"id": "2", "title": "料理", "url": "https://example.com/2"},
    ]}]
    selected = _filter_items(payloads, ["s"], ["AI"], [], [])
    assert [i["id"] for i in selected] == ["1"]
    pinned = _pin_and_limit(selected, ["1"], [], 10)
    assert pinned[0]["selection_mode"] == "pinned"

    print("SELF TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
