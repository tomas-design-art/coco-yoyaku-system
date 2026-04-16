import asyncio
# Import the app to trigger all model registrations
import app.main  # noqa: F401
from app.services.patient_match import find_existing_patient, normalize_name, normalize_phone, _name_matches_patient

def test_normalize():
    """Pure function tests - no DB needed"""
    print("=== normalize_name tests ===")
    cases = [
        ("時田 信", "時田信"),
        ("時田　信", "時田信"),     # 全角スペース
        ("時田信", "時田信"),       # スペースなし
        (" 時田  信 ", "時田信"),   # 余分なスペース
    ]
    for inp, expected in cases:
        result = normalize_name(inp)
        status = "OK" if result == expected else "FAIL"
        print(f'  [{status}] normalize_name("{inp}") = "{result}" (expected "{expected}")')

    print()
    print("=== normalize_phone tests ===")
    phone_cases = [
        ("09040034681", "09040034681"),
        ("090-4003-4681", "09040034681"),
        ("０９０４００３４６８１", "09040034681"),  # 全角
        ("+819040034681", "09040034681"),            # 国際番号
    ]
    for inp, expected in phone_cases:
        result = normalize_phone(inp)
        status = "OK" if result == expected else "FAIL"
        print(f'  [{status}] normalize_phone("{inp}") = "{result}" (expected "{expected}")')

    print()
    print("=== _name_matches_patient tests ===")
    # Simulate a Patient-like object
    class FakePatient:
        def __init__(self, name, last_name=None, first_name=None):
            self.name = name
            self.last_name = last_name
            self.first_name = first_name

    match_cases = [
        # (input_name, patient, expected)
        ("時田信", FakePatient("時田 信", "時田", "信"), True),
        ("時田信", FakePatient("時田信", None, None), True),
        ("時田信", FakePatient("", "時田", "信"), True),          # name empty but last+first match
        ("時田信", FakePatient("山田 太郎", "山田", "太郎"), False),
    ]
    for norm_input, patient, expected in match_cases:
        result = _name_matches_patient(normalize_name(norm_input), patient)
        status = "OK" if result == expected else "FAIL"
        print(f'  [{status}] name="{patient.name}" last="{patient.last_name}" first="{patient.first_name}" -> {result} (expected {expected})')

    print()
    print("=== Scenario: Web予約 時田 信 + 09040034681 ===")
    # Simulate existing patient in DB
    existing = FakePatient("時田 信", "時田", "信")
    existing.phone = "09040034681"
    existing.line_id = None
    existing.id = 42

    web_name = "時田 信"
    web_phone = "09040034681"
    norm_phone_val = normalize_phone(web_phone)
    norm_name_val = normalize_name(web_name)

    # Step 1: phone match
    phone_match = existing.phone and normalize_phone(existing.phone) == norm_phone_val
    print(f"  Phone match: {phone_match}")
    # Step 2: name match
    name_match = _name_matches_patient(norm_name_val, existing)
    print(f"  Name match: {name_match}")
    print(f"  -> Would return existing patient id={existing.id}: {phone_match or name_match}")
    print()

    if phone_match:
        print("PASS: Phone match alone is sufficient - same person detected!")
    else:
        print("FAIL: Phone match didn't work")

test_normalize()

import asyncio
from app.services.patient_match import find_existing_patient, normalize_name, normalize_phone, _name_matches_patient
from app.database import async_session
from sqlalchemy import select
from app.models.patient import Patient

async def test():
    async with async_session() as db:
        result = await db.execute(select(Patient))
        patients = result.scalars().all()
        print("=== All patients ===")
        for p in patients:
            print(f'  id={p.id} name="{p.name}" last_name="{p.last_name}" first_name="{p.first_name}" phone="{p.phone}"')

        print()
        print('=== Test matching: name="時田 信" phone="09040034681" ===')
        match = await find_existing_patient(db, name="時田 信", phone="09040034681")
        if match:
            print(f"MATCHED: id={match.id} name={match.name}")
        else:
            print("NO MATCH - would create new patient (BUG!)")

        print()
        print("=== Normalize debug ===")
        print(f'normalize_name("時田 信") = "{normalize_name("時田 信")}"')
        print(f'normalize_phone("09040034681") = "{normalize_phone("09040034681")}"')
        for p in patients:
            nn = normalize_name(p.name)
            np_ = normalize_phone(p.phone)
            print(f'  Patient id={p.id}: normalize_name("{p.name}")="{nn}" normalize_phone("{p.phone}")="{np_}"')
            if p.last_name or p.first_name:
                combined = normalize_name(f"{p.last_name or ''}{p.first_name or ''}")
                print(f'    last+first combined: "{combined}"')

asyncio.run(test())
