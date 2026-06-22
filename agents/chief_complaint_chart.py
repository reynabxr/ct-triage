from __future__ import annotations

CHIEF_COMPLAINT_ICD10_CHART: dict[str, str] = {
    "D69.6": "thrombocytopenia, unspecified",
    "G40.89": "other seizures",
    "I63.9": "cerebral infarction, unspecified",
    "I77.9": "disorder of arteries and arterioles, unspecified",
    "I87.2": "venous insufficiency, chronic",
    "K62.5": "hemorrhage of anus and rectum",
    "K92.2": "gastrointestinal hemorrhage, unspecified",
    "M62.81": "muscle weakness",
    "M79.60": "pain in limb, unspecified",
    "N19": "renal failure, unspecified",
    "N50.819": "testicular pain, unspecified",
    "N93.9": "abnormal uterine/vaginal bleeding, unspecified",
    "R06.00": "dyspnea, unspecified",
    "R07.9": "chest pain, unspecified",
    "R10.84": "generalized abdominal pain",
    "R11.10": "vomiting, unspecified",
    "R26": "abnormalities of gait and mobility",
    "R31.9": "hematuria, unspecified",
    "R40.20": "coma, unspecified",
    "R42": "dizziness and giddiness",
    "R50.9": "fever, unspecified",
    "R51.9": "headache, unspecified",
    "R53": "malaise and fatigue",
    "R55": "syncope and collapse",
    "R60.9": "edema, unspecified",
    "S09.93": "unspecified injury of face",
    "T07": "unspecified multiple injuries",
    "T18.9": "foreign body of alimentary tract, unspecified",
    "T50.901A": "poisoning by unspecified drugs/medicaments, accidental, initial encounter",
    "T79.9": "unspecified early complication of trauma",
    "T82.4": "mechanical complication of vascular dialysis catheter",
    "T88.9XXA": "unspecified complication of surgical and medical care, initial encounter",
    "U07.1": "COVID-19",
    "W19": "unspecified fall",
    "Z03.89": "encounter for observation for other suspected diseases ruled out",
    "Z98.890": "other specified postprocedural states",
}


def chief_complaint_description_for_code(code: str | None) -> str | None:
    if code is None:
        return None
    normalized = code.strip().upper()
    if not normalized:
        return None
    return CHIEF_COMPLAINT_ICD10_CHART.get(normalized)
