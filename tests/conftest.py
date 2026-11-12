import pytest

from signpad.samples import build_sample_docx, build_sample_pdf, build_sample_signature


@pytest.fixture
def sample_docx(tmp_path):
    return build_sample_docx(tmp_path / "agreement.docx")


@pytest.fixture
def sample_pdf(tmp_path):
    return build_sample_pdf(tmp_path / "consent.pdf")


@pytest.fixture
def signature_png():
    return build_sample_signature()


class FakePad:
    """Stands in for the browser: returns a canned signature and approval."""

    def __init__(self, png, approve=True, decline=False):
        self.png, self.approve, self.decline = png, approve, decline
        self.messages, self.reviews = [], []

    def status(self, message):
        self.messages.append(message)

    def request_signature(self, signer, purpose):
        return None if self.decline else self.png

    def request_review(self, summary, preview_pdf, files):
        self.reviews.append((summary, preview_pdf, files))
        return self.approve, "" if self.approve else "move it"


@pytest.fixture
def fake_pad(signature_png):
    return FakePad(signature_png)
