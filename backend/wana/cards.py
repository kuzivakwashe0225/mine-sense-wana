"""Target cards: plain-language explanation of a ranked cell in English and ChiShona.

ChiShona strings are a working draft and must be reviewed by Shona-speaking miners before use.
"""
from __future__ import annotations

import numpy as np

T = {
 "en": {
  "conf": ["Low", "Medium", "High"],
  "pos": {"um_host": "On or next to ultramafic (serpentinite) rock, where chrome pods form",
          "shear": "Close to a shear or fault zone", "mgoh": "Satellite sees serpentine minerals at the surface",
          "ferric": "Iron-stained soil, typical over weathered ultramafic rock",
          "swir_oh": "Satellite sees OH-bearing minerals (serpentine, talc, clays)",
          "ridge": "Ridge ground, where hard ultramafic rock stands up",
          "magnetics": "Magnetic high, typical of ultramafic rock"},
  "neg": {"um_host": "Mapped as granite or greenstone, not ultramafic", "shear": "Far from mapped shears",
          "mgoh": "Weak serpentine signal from satellite", "ferric": "Little iron staining",
          "swir_oh": "Weak OH-mineral signal", "ridge": "Low ground with soil cover", "magnetics": "Low magnetics"},
  "check": {"um_host": "Look for dark green, soapy-feeling serpentinite outcrop",
            "shear": "Walk along the shear line; pods are often strung out along it",
            "mgoh": "Check bare patches for pale green-grey weathered rock",
            "ferric": "Red-brown soil over green rock: take a surface sample, do not dig",
            "swir_oh": "Look for talc or soapstone fragments in the soil",
            "ridge": "Check the ridge crest and its foot for black float",
            "magnetics": "Black grains that cling weakly to a magnet are a good sign"},
  "missing": "No {layer} data here, so confidence is lower.",
  "s_slope": "Steep ground: pit walls can collapse. Do not dig under overhangs.",
  "s_old": "Old workings recorded nearby: open pits and shafts are a falling hazard.",
  "s_none": "No special hazard flagged. Normal field care applies.",
  "rights": "Mineral rights not verified, so not shown. Confirm with the Mining Commissioner before any work.",
  "disclaimer": "Wana shows places worth checking. It does not prove chrome is there and does not give anyone the right to mine.",
  "loc_miner": "Shown to about 1 km. Exact point available to registered users through the geologist.",
 },
 "sn": {
  "conf": ["Kwakaderera", "Kwepakati", "Kwakakwira"],
  "pos": {"um_host": "Iri padombo re-serpentinite kana pedyo naro, panowanikwa chrome",
          "shear": "Iri pedyo nemutsetse we-shear kana fault", "mgoh": "Satellite inoona maminerari e-serpentine pamusoro",
          "ferric": "Ivhu rine ngura yesimbi", "swir_oh": "Satellite inoona maminerari ane OH (serpentine, talc)",
          "ridge": "Pamusoro pegomo, panomira dombo rakaoma", "magnetics": "Magineti yakakwira"},
  "neg": {"um_host": "Mepu inoti granite kana greenstone", "shear": "Kure nemitsetse ye-shear",
          "mgoh": "Satellite haioni serpentine zvakanyanya", "ferric": "Hapana ngura yakawanda",
          "swir_oh": "Chiratidzo che-OH chiri pasi", "ridge": "Pakaderera pane ivhu rakawanda", "magnetics": "Magineti yakaderera"},
  "check": {"um_host": "Tsvagai dombo rakasvibirira, rinotsvedza sesipo",
            "shear": "Fambai nemutsetse we-shear; chrome inowanzoteedzana nawo",
            "mgoh": "Tarisai nzvimbo dzisina huswa mutsvage dombo regirini-grey",
            "ferric": "Ivhu dzvuku pamusoro pedombo regirini: torai sample yepamusoro, musachera",
            "swir_oh": "Tsvagai zvidimbu zve-talc kana soapstone muvhu",
            "ridge": "Tarisai pamusoro nepasi pegomo mutsvage zvidimbu zvitema",
            "magnetics": "Zvidimbu zvitema zvinonamatira kumagineti chiratidzo chakanaka"},
  "missing": "Hapana data re{layer} pano, saka kuvimba kwakaderera.",
  "s_slope": "Pakaramba: madziro emakomba anogona kuwira. Musachera pasi pedombo rakarembera.",
  "s_old": "Makomba ekare ari pedyo: munogona kuwira mumakomba nemashaft.",
  "s_none": "Hapana njodzi yakaratidzwa. Ngwarirai sezvamunogara muchiita.",
  "rights": "Kodzero dzekuchera hadzina kusimbiswa, saka hadziratidzwe. Bvunzai Mining Commissioner musati mashanda.",
  "disclaimer": "Wana inoratidza nzvimbo dzakakodzera kuongororwa. Haisi humbowo hwekuti chrome iripo uye haipe munhu kodzero yekuchera.",
  "loc_miner": "Inoratidzwa kusvika pa1 km. Nzvimbo chaiyo inowanikwa kubudikidza negeologist.",
 },
}


def build_card(model, grids, stack_X, slope, r, c, occ_rc, lang="en", target=None, role="miner", loc=None):
    L = T.get(lang, T["en"])
    feats = model["features"]
    z = grids["z"][r, c]
    coef = np.array(model["coef_mean"])
    contrib = coef * z
    raw = stack_X[:, r, c]
    order = np.argsort(-contrib)
    pos = [{"feature": feats[i], "label": model["feature_labels"][feats[i]], "value": float(contrib[i]),
            "text": L["pos"][feats[i]]} for i in order if contrib[i] > 0.05][:3]
    neg = [{"feature": feats[i], "label": model["feature_labels"][feats[i]], "value": float(contrib[i]),
            "text": L["neg"][feats[i]]} for i in order[::-1] if contrib[i] < -0.05 and np.isfinite(raw[i])][:2]
    missing = [L["missing"].format(layer=model["feature_labels"][feats[i]]) for i in range(len(feats))
               if not np.isfinite(raw[i]) and abs(coef[i]) > 0.1]
    checks = [L["check"][p["feature"]] for p in pos] or [L["check"]["um_host"]]
    res = model["grid"]["res"]
    flags = []
    if slope[r, c] > 15:
        flags.append(L["s_slope"])
    if any((r - a) ** 2 + (c - b) ** 2 < (400 / res) ** 2 for a, b in occ_rc):
        flags.append(L["s_old"])
    conf = int(grids["conf"][r, c])
    return {
        "target": target, "score": round(float(grids["wscore"][r, c]), 1),
        "percentile_top": max(1, round(100 - float(grids["score"][r, c]))),
        "confidence": ["Low", "Medium", "High"][conf], "confidence_label": L["conf"][conf],
        "why": pos, "against": neg, "missing": missing, "check_first": checks,
        "safety": flags or [L["s_none"]], "safety_flagged": bool(flags),
        "rights": L["rights"], "disclaimer": L["disclaimer"], "location": loc,
        "location_note": L["loc_miner"] if role == "miner" else None,
        "site": {"slope_deg": round(float(slope[r, c]), 1)} if role == "geologist" else None,
        "model_version": model["version"], "sample_data": model["any_sample"],
    }
