"""Sign a document from Python, choosing the slot yourself.

    python examples/sign_without_agent.py form.docx

Opens the signing pad, waits for your signature, lists the slots, and asks
which one to use.
"""
import sys
from pathlib import Path

from signpad.documents import open_document
from signpad.pad import PadServer


def main(path: str) -> None:
    doc = open_document(path)
    slots = doc.slots()
    for s in slots:
        print(f"{s.id:>4}  {s.kind:<11} {s.label[:50]!r}  {s.current_text!r}")
    slot_id = input("Slot for your signature (e.g. S1): ").strip()

    with PadServer() as pad:
        print(f"Draw your signature at {pad.url}")
        png = pad.request_signature("you", f"Signature for {doc.path.name}, slot {slot_id}.")
        if png is None:
            print("Declined.")
            return
        if doc.slot(slot_id).current_text:
            doc.clear_slot(slot_id)           # replace a typed name
        doc.place_image(slot_id, png)
        out = doc.save(doc.path.with_name(f"{doc.path.stem} - signed{doc.path.suffix}"))
        pad.status(f"Saved {out}")
        print(f"Saved {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path("demo/sample_agreement.docx")))
