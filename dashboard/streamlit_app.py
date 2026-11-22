"""Streamlit operator dashboard for KisanVaani.

Lists claims, shows claim details/photos, and generates claim PDFs.
Run as: streamlit run dashboard/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import DASHBOARD_PASSWORD, DATABASE_URL  # noqa: E402
from db.models import Claim, ClaimStatus, Media  # noqa: E402
from services.pdf_generator import generate_claim_pdf  # noqa: E402


@st.cache_resource
def get_session_factory():
    """Create a cached SQLAlchemy session factory for the dashboard."""
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def require_password() -> bool:
    """Simple password gate for the operator dashboard."""
    if st.session_state.get("authed"):
        return True
    st.title("KisanVaani Operator Dashboard")
    st.caption("Enter dashboard password to continue.")
    pw = st.text_input("Dashboard password", type="password")
    if st.button("Login"):
        if pw and pw == DASHBOARD_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Invalid password.")
    return False


def load_claims(session):
    """Load claims newest-first for the dashboard list."""
    return session.execute(select(Claim).order_by(Claim.created_at.desc())).scalars().all()


def load_claim(session, claim_id: str):
    """Load a single claim by ID."""
    return session.get(Claim, claim_id)


def load_photos(session, claim_id: str) -> list[Media]:
    """Load image media for a claim."""
    stmt = select(Media).where(Media.claim_id == claim_id, Media.media_type == "image").order_by(Media.created_at.asc())
    return session.execute(stmt).scalars().all()


def status_label(status: ClaimStatus | str) -> str:
    """Convert status enum/string to display label."""
    return status.value if hasattr(status, "value") else str(status)


def render_claim_list(claims: list[Claim]) -> str | None:
    """Render claims table and selection control."""
    st.subheader("Claims")
    if not claims:
        st.info("No claims yet.")
        return None

    rows = [{
        "Claim ID": c.id, "Phone": c.farmer_phone, "Status": status_label(c.status),
        "Crop": c.crop or "-", "Damage": c.damage_type or "-", "Village": c.village or "-",
        "Date": c.incident_date or "-", "Updated": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "-",
    } for c in claims]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    options = [c.id for c in claims]
    selected = st.session_state.get("selected_claim_id")
    index = options.index(selected) if selected in options else 0
    return st.selectbox("Select claim", options=options, index=index)


def render_claim_detail(session, claim: Claim) -> None:
    """Render claim details, photos, and PDF generation action."""
    st.subheader(f"Claim {claim.id}")
    cols = st.columns(4)
    cols[0].metric("Status", status_label(claim.status))
    cols[1].metric("Confidence", f"{claim.confidence:.2f}")
    cols[2].metric("Missing", ", ".join(claim.missing_fields) if claim.missing_fields else "None")
    photos = load_photos(session, claim.id)
    cols[3].metric("Photos", len(photos))

    left, right = st.columns(2)
    with left:
        st.markdown("**Farmer phone**")
        st.write(claim.farmer_phone)
        st.markdown("**Crop**")
        st.write(claim.crop or "-")
        st.markdown("**Damage type**")
        st.write(claim.damage_type or "-")
    with right:
        st.markdown("**Village/Location**")
        st.write(claim.village or "-")
        st.markdown("**Incident date**")
        st.write(claim.incident_date or "-")
        st.markdown("**PDF path**")
        st.write(claim.pdf_path or "-")

    st.markdown("### Photos")
    if photos:
        img_cols = st.columns(min(3, len(photos)))
        for i, media in enumerate(photos):
            path = Path(media.file_path)
            with img_cols[i % len(img_cols)]:
                if path.exists():
                    st.image(str(path), caption=path.name, use_container_width=True)
                else:
                    st.warning(f"Missing file: {media.file_path}")
    else:
        st.info("No photos attached yet.")

    can_generate = not claim.missing_fields and len(photos) >= 1
    if st.button("Generate PDF", type="primary", disabled=not can_generate):
        try:
            pdf_path = generate_claim_pdf(claim, [m.file_path for m in photos])
            claim.pdf_path = pdf_path
            claim.status = ClaimStatus.PDF_GENERATED
            session.commit()
            st.success(f"PDF generated: {pdf_path}")
            with open(pdf_path, "rb") as f:
                st.download_button("Download PDF", data=f.read(), file_name=Path(pdf_path).name, mime="application/pdf")
            st.rerun()
        except Exception as exc:
            session.rollback()
            st.error(f"PDF generation failed: {exc}")

    if claim.pdf_path and Path(claim.pdf_path).exists():
        with open(claim.pdf_path, "rb") as f:
            st.download_button("Download existing PDF", data=f.read(), file_name=Path(claim.pdf_path).name,
                               mime="application/pdf", key=f"dl-{claim.id}")


def main() -> None:
    """Render the operator dashboard."""
    st.set_page_config(page_title="KisanVaani Dashboard", layout="wide")
    if not require_password():
        return

    st.title("KisanVaani Operator Dashboard")
    st.caption("Review claims, inspect photos, and generate insurer-ready PDFs.")
    session_factory = get_session_factory()
    with session_factory() as session:
        claims = load_claims(session)
        claim_id = render_claim_list(claims)
        st.session_state["selected_claim_id"] = claim_id
        if claim_id:
            claim = load_claim(session, claim_id)
            if claim:
                st.divider()
                render_claim_detail(session, claim)


if __name__ == "__main__":
    # Prefer: streamlit run dashboard/streamlit_app.py
    main()
