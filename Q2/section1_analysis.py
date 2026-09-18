import csv
import glob
import re
import os

notices = {}

for f in glob.glob(r"data_2/notices/*.csv"):
    with open(f, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            notices[r["notice_id"]] = r

pairs = list(
    csv.DictReader(
        open(r"data_2/labelled_pairs.csv", encoding="utf-8")
    )
)

boiler = re.compile(
    r"(national procurement aggregation service|state procurement cell)",
    re.I
)

ref = re.compile(
    r"\b(?:npas|spc|pwd|mc|tn)[-/A-Z0-9]*\b",
    re.I
)

date = re.compile(
    r"\b(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b"
)

num = re.compile(
    r"\b\d+(?:[.,]\d+)*\b"
)


def tokens(text, mode):
    text = text.lower()

    if mode == "normalized":
        text = boiler.sub(" ", text)
        text = ref.sub(" ", text)
        text = date.sub(" ", text)
        text = num.sub(" ", text)

    return re.findall(r"[a-z]+", text)


def shingles(text, mode):
    t = tokens(text, mode)

    return set(
        " ".join(t[i:i+3])
        for i in range(max(0, len(t) - 2))
    )


def jaccard(a, b):
    union = a | b

    if not union:
        return 0.0

    return len(a & b) / len(union)


os.makedirs("output", exist_ok=True)

results = []

results.append("Q2 SECTION A - REPRESENTATION COMPARISON")
results.append("========================================")
results.append(f"Notices: {len(notices)}")
results.append(f"Labelled pairs: {len(pairs)}")
results.append("")

for mode in ["raw", "normalized"]:

    values = {
        "same": [],
        "different": []
    }

    for p in pairs:

        a = notices[p["notice_id_a"]]
        b = notices[p["notice_id_b"]]

        text_a = a["title"] + " " + a["body"]
        text_b = b["title"] + " " + b["body"]

        sh_a = shingles(text_a, mode)
        sh_b = shingles(text_b, mode)

        score = jaccard(sh_a, sh_b)

        values[p["label"]].append(score)

    same_mean = sum(values["same"]) / len(values["same"])
    diff_mean = sum(values["different"]) / len(values["different"])

    line = (
        f"{mode.upper()}: "
        f"SAME mean={same_mean:.4f}, "
        f"min={min(values['same']):.4f}, "
        f"max={max(values['same']):.4f}; "
        f"DIFFERENT mean={diff_mean:.4f}, "
        f"min={min(values['different']):.4f}, "
        f"max={max(values['different']):.4f}"
    )

    print(line)
    results.append(line)

with open(
    "output/sectionA_representation_comparison.txt",
    "w",
    encoding="utf-8"
) as f:
    f.write("\n".join(results))

print("")
print("Evidence saved to:")
print("output/sectionA_representation_comparison.txt")





# ============================================================
# SECTION B - MINHASH ESTIMATION ACCURACY
# ============================================================

import hashlib


def hash_shingle(shingle, seed):
    data = (str(seed) + "|" + shingle).encode("utf-8")
    return int.from_bytes(
        hashlib.sha256(data).digest()[:8],
        "big"
    )


def minhash_signature(shingles_set, size):
    if not shingles_set:
        return [0] * size

    return [
        min(hash_shingle(sh, seed) for sh in shingles_set)
        for seed in range(size)
    ]


def minhash_similarity(sig_a, sig_b):
    return sum(
        a == b for a, b in zip(sig_a, sig_b)
    ) / len(sig_a)


print("")
print("SECTION B - MINHASH ACCURACY")
print("============================")

# Use a representative sample of the labelled pairs
# for sizing the estimator before the full evaluation.
sample_pairs = pairs[:200]

signature_sizes = [64, 128, 256]

b_results = []

for size in signature_sizes:

    errors = []

    for p in sample_pairs:

        a = notices[p["notice_id_a"]]
        b = notices[p["notice_id_b"]]

        text_a = a["title"] + " " + a["body"]
        text_b = b["title"] + " " + b["body"]

        sh_a = shingles(text_a, "normalized")
        sh_b = shingles(text_b, "normalized")

        exact = jaccard(sh_a, sh_b)

        sig_a = minhash_signature(sh_a, size)
        sig_b = minhash_signature(sh_b, size)

        estimated = minhash_similarity(sig_a, sig_b)

        errors.append(
            abs(estimated - exact)
        )

    mean_error = sum(errors) / len(errors)
    max_error = max(errors)
    within_005 = sum(
        error <= 0.05 for error in errors
    ) / len(errors) * 100

    line = (
        f"SIZE={size}: "
        f"MEAN_ABS_ERROR={mean_error:.4f}, "
        f"MAX_ABS_ERROR={max_error:.4f}, "
        f"WITHIN_0.05={within_005:.2f}%"
    )

    print(line)
    b_results.append(line)


with open(
    "output/sectionB_minhash_accuracy.txt",
    "w",
    encoding="utf-8"
) as f:

    f.write("Q2 SECTION B - MINHASH ACCURACY\n")
    f.write("==============================\n")
    f.write("Representation: normalized word 3-grams\n")
    f.write("Exact similarity: Jaccard\n")
    f.write("Estimator: MinHash\n")
    f.write("Sizing sample: first 200 labelled pairs\n\n")

    for line in b_results:
        f.write(line + "\n")