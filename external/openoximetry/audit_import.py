"""EXPLORATORY audit script. The meaning of so2 is UNRESOLVED; nothing here is a research output and nothing is imported or trained.
Usage: python audit_import.py [path-to-openoximetry-folder]   (default: the folder this file lives in)"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
R = str(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent)
bg = pd.read_csv(f"{R}/raw/bloodgas.csv", low_memory=False)
po = pd.read_csv(f"{R}/raw/pulseoximeter.csv", low_memory=False, dtype=str)
sp = pd.read_csv(f"{R}/raw/spectrophotometer.csv", low_memory=False)
en = pd.read_csv(f"{R}/raw/encounter.csv", low_memory=False)
out = {}

# ---- A. encounter -> patient
m_en = en.drop_duplicates("encounter_id").set_index("encounter_id").patient_id
def multi(df, name):
    g = df.dropna(subset=["patient_id"]).groupby("encounter_id").patient_id.nunique()
    bad = g[g > 1]
    vs_enc = df.dropna(subset=["patient_id"]).drop_duplicates(["encounter_id", "patient_id"])
    vs_enc = vs_enc[vs_enc.encounter_id.isin(m_en.index)]
    mism = int((vs_enc.patient_id != vs_enc.encounter_id.map(m_en)).sum())
    return {"encounters": int(df.encounter_id.nunique()), "encounters_with_more_than_one_patient_id": int(len(bad)), "(encounter,patient) pairs disagreeing with encounter.csv": mism,
            "encounters_not_in_encounter_csv": int((~df.encounter_id.isin(m_en.index)).groupby(df.encounter_id).first().sum())}
out["A_patient_mapping"] = {"encounter.csv rows": len(en), "encounter.csv duplicate encounter_id": int(en.encounter_id.duplicated().sum()),
                            "bloodgas": multi(bg, "bg"), "spectrophotometer": multi(sp, "sp")}
ex = bg.dropna(subset=["patient_id"]).groupby("encounter_id").patient_id.nunique(); ex = ex[ex > 1].index[:2]
for e in ex:
    out.setdefault("A_examples", []).append({"encounter": e[-8:], "bloodgas patient ids": [p[-6:] for p in bg[bg.encounter_id == e].patient_id.dropna().unique()], "encounter.csv patient": str(m_en.get(e, "absent"))[-6:]})

# ---- B. pulse-ox, target devices
po["sample"] = pd.to_numeric(po.sample_number, errors="coerce")
po["dev_str"] = po.device.fillna("").str.replace(" ", "", regex=False)
po["dev_id"] = pd.to_numeric(po.dev_str, errors="coerce").floordiv(1)
po["probe"] = ((pd.to_numeric(po.dev_str, errors="coerce") % 1) * 100).round().astype("Int64")
po["spo2"] = pd.to_numeric(po.saturation, errors="coerce"); po["pi_n"] = pd.to_numeric(po.pi, errors="coerce")
tg = po[po.dev_id.isin([55, 60, 73, 76])].copy()
rep = []
for d, s in tg.groupby("dev_id"):
    pn = s.pi_n
    rep.append({"device": int(d), "rows": len(s), "PI_missing": int(s.pi.isna().sum()), "PI_missing_pct": round(100 * s.pi.isna().mean(), 1), "PI_min": float(pn.min()), "PI_median": float(pn.median()), "PI_max": float(pn.max()),
                "device_string_forms": s.dev_str.value_counts().to_dict()})
out["B_target_device_PI"] = rep
# exclusion cascade for target devices (each row counted under the FIRST failing reason)
tg["reason"] = ""
def mark(mask, why):
    sel = mask & (tg.reason == "")
    tg.loc[sel, "reason"] = why; return int(sel.sum())
excl = {}
excl["device string malformed/unparsable"] = mark(tg.dev_id.isna(), "device string malformed")
excl["SpO2 not numeric (text note in the file)"] = mark(tg.spo2.isna(), "spo2 text")
excl["SpO2 outside 50-100"] = mark(~tg.spo2.between(50, 100), "spo2 range")
excl["sample_number missing"] = mark(tg["sample"].isna(), "no sample")
excl["PI missing (device string form carries no PI)"] = mark(tg.pi_n.isna(), "pi missing")
excl["PI <= 0 or non-numeric"] = mark(~(tg.pi_n > 0), "pi bad")
out["B_exclusions_pulseox_target_devices"] = {"source_rows": len(tg), **excl, "remaining": int((tg.reason == "").sum())}
ok = tg[tg.reason == ""]

# ---- C. pairing multiplicity vs blood gas
bgv = bg[bg.so2.between(50, 100)]
cnt = bgv.groupby(["encounter_id", "sample"]).size().rename("n_bg")
ok = ok.join(cnt, on=["encounter_id", "sample"])
out["C_pairing"] = {"pulseox rows (target, clean)": len(ok), "no blood gas row for (encounter,sample)": int(ok.n_bg.isna().sum()),
                    "exactly 1 blood gas row": int((ok.n_bg == 1).sum()), "2 blood gas rows": int((ok.n_bg == 2).sum()), "3+ blood gas rows": int((ok.n_bg >= 3).sum())}
sp2 = bgv.groupby(["encounter_id", "sample"]).so2.agg(lambda x: x.max() - x.min())
two = sp2[cnt[sp2.index] >= 2]
out["C_pairing"]["so2 spread inside (encounter,sample) groups with >=2 rows: median/p90/max"] = [round(float(two.median()), 2), round(float(two.quantile(0.9)), 2), round(float(two.max()), 2)]
out["C_pairing"]["bloodgas exact duplicate rows"] = int(bg.duplicated().sum())

# ---- D. palmar skin colour
pm = sp[sp.group.eq("Palmar (C)")].copy()
pm["valid"] = pm[["lab_l", "lab_a", "lab_b"]].notna().all(axis=1) & (pm.lab_l > 0)
pm["ita"] = np.degrees(np.arctan2(pm.lab_l - 50, pm.lab_b))
pe = pm[pm.valid].groupby("encounter_id").agg(n=("ita", "size"), ita_spread=("ita", lambda x: x.max() - x.min()), ita=("ita", "mean"))
out["D_palmar"] = {"palmar rows": len(pm), "rows with missing Lab or L*<=0": int((~pm.valid).sum()), "encounters with >=1 valid palmar reading": len(pe),
                   "readings per encounter (valid)": pe.n.value_counts().sort_index().to_dict(), "ITA spread among repeats: median/p90/max": [round(float(pe.ita_spread.median()), 2), round(float(pe.ita_spread.quantile(.9)), 2), round(float(pe.ita_spread.max()), 2)],
                   "ITA (per-reading) min/max": [round(float(pm[pm.valid].ita.min()), 1), round(float(pm[pm.valid].ita.max()), 1)]}
ok = ok.join(pe[["ita"]], on="encounter_id")
out["D_palmar"]["clean target pulse-ox rows with palmar ITA"] = int(ok.ita.notna().sum())

# ---- E. size of the usable set if (and only if) pairing were restricted to unambiguous 1:1 cases
u = ok[(ok.n_bg == 1) & ok.ita.notna()]
pid = en.drop_duplicates("encounter_id").set_index("encounter_id").patient_id
out["E_if_restricted_to_one_to_one"] = {"rows": len(u), "encounters": int(u.encounter_id.nunique()), "patients": int(u.encounter_id.map(pid).nunique()), "per device": u.dev_id.value_counts().astype(int).to_dict()}
json.dump(out, open(f"{R}/reports/import_audit.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str)[:6500])
