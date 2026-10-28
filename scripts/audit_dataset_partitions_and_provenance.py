import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.prepare_dataset import extract_scene_group_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("audit_partitions_provenance")


def main():
    manifest_path = Path("data/manifest.json")
    licensing_path = Path("data/dataset_licensing_evidence.json")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    with open(licensing_path, encoding="utf-8") as f:
        licensing = json.load(f)

    items = manifest.get("items", [])
    logger.info("Total items in manifest: %d", len(items))

    # Split breakdowns
    split_items = defaultdict(list)
    for it in items:
        split_items[it.get("split")].append(it)

    print("\n=== DATASET PARTITION AUDIT ===")
    print(f"Total manifest items: {len(items)}")
    for split_name in ["train", "val", "test"]:
        split_list = split_items[split_name]
        c0 = sum(1 for it in split_list if it.get("label") == 0)
        c1 = sum(1 for it in split_list if it.get("label") == 1)
        mf_hf = sum(1 for it in split_list if "moviefights" in it["path"].lower() or "hockeyfight" in it["path"].lower())
        auth = len(split_list) - mf_hf
        print(f"Split '{split_name}': total={len(split_list)}, Class 0={c0}, Class 1={c1}, Excluded(MovieFights/HockeyFight)={mf_hf}, Authorized Surveillance={auth}")

    # Check path overlap
    train_paths = {it["path"] for it in split_items["train"]}
    val_paths = {it["path"] for it in split_items["val"]}
    test_paths = {it["path"] for it in split_items["test"]}

    tv_overlap = train_paths & val_paths
    tt_overlap = train_paths & test_paths
    vt_overlap = val_paths & test_paths

    print("\n=== PATH OVERLAP AUDIT ===")
    print(f"Train & Val path overlap: {len(tv_overlap)}")
    print(f"Train & Test path overlap: {len(tt_overlap)}")
    print(f"Val & Test path overlap: {len(vt_overlap)}")

    # Check SHA-256 hash overlap
    train_hashes = {it.get("sha256") for it in split_items["train"] if it.get("sha256")}
    val_hashes = {it.get("sha256") for it in split_items["val"] if it.get("sha256")}
    test_hashes = {it.get("sha256") for it in split_items["test"] if it.get("sha256")}

    tv_hash_overlap = train_hashes & val_hashes
    tt_hash_overlap = train_hashes & test_hashes
    vt_hash_overlap = val_hashes & test_hashes

    print("\n=== BITWISE SHA-256 HASH OVERLAP AUDIT ===")
    print(f"Train & Val hash overlap: {len(tv_hash_overlap)}")
    print(f"Train & Test hash overlap: {len(tt_hash_overlap)}")
    print(f"Val & Test hash overlap: {len(vt_hash_overlap)}")

    # Check scene-prefix group leakage between val and test
    val_groups = defaultdict(list)
    for it in split_items["val"]:
        gid, conf = extract_scene_group_id(Path(it["path"]).name, "")
        if conf == "scene_prefix_verified":
            val_groups[gid].append(it["path"])

    test_groups = defaultdict(list)
    for it in split_items["test"]:
        gid, conf = extract_scene_group_id(Path(it["path"]).name, "")
        if conf == "scene_prefix_verified":
            test_groups[gid].append(it["path"])

    group_leakage = set(val_groups.keys()) & set(test_groups.keys())
    print("\n=== SCENE-PREFIX GROUP LEAKAGE AUDIT (VAL vs TEST) ===")
    print(f"Verified scene groups in Val: {len(val_groups)}")
    print(f"Verified scene groups in Test: {len(test_groups)}")
    print(f"Scene group ID overlaps between Val and Test: {len(group_leakage)}")
    if group_leakage:
        print(f"Leaked scene group IDs: {group_leakage}")

    # Check provenance status
    print("\n=== SUB-SOURCE PROVENANCE & LEGAL RIGHTS AUDIT ===")
    prov = licensing.get("evaluated_datasets_provenance", {})
    for src, details in prov.items():
        print(f"Sub-source: {src}")
        print(f"  Canonical Source: {details.get('original_publisher_and_canonical_source')}")
        print(f"  License: {details.get('exact_license_text_or_agreement')[:80]}...")
        print(f"  Model Training Permitted: {details.get('expressly_permitted_uses', {}).get('model_training')}")
        print(f"  Commercial Use Permitted: {details.get('expressly_permitted_uses', {}).get('commercial_use')}")
        print(f"  Final Governance Status: {details.get('final_status')}")

    out_data = {
        "total_manifest_items": len(items),
        "split_counts": {
            "train": {"total": len(split_items["train"]), "authorized": len(split_items["train"]) - sum(1 for it in split_items["train"] if "moviefights" in it["path"].lower() or "hockeyfight" in it["path"].lower())},
            "val": {"total": len(split_items["val"]), "authorized": len(split_items["val"]) - sum(1 for it in split_items["val"] if "moviefights" in it["path"].lower() or "hockeyfight" in it["path"].lower())},
            "test": {"total": len(split_items["test"]), "authorized": len(split_items["test"]) - sum(1 for it in split_items["test"] if "moviefights" in it["path"].lower() or "hockeyfight" in it["path"].lower())},
        },
        "path_leakage": {"train_val": len(tv_overlap), "train_test": len(tt_overlap), "val_test": len(vt_overlap)},
        "hash_leakage": {"train_val": len(tv_hash_overlap), "train_test": len(tt_hash_overlap), "val_test": len(vt_hash_overlap)},
        "scene_prefix_leakage_val_test": len(group_leakage),
        "sub_source_provenance": prov,
    }

    out_file = Path("artifacts/reports/validation/dataset_partition_provenance_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2)
    logger.info("Saved partition provenance audit to: %s", out_file)


if __name__ == "__main__":
    main()
