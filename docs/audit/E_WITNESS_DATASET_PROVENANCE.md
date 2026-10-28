# E-WITNESS — Dataset Rights, Provenance, and Governance Audit Report

**Document ID:** `EW-AUDIT-DATA-PROV-2026-10-26-REV2`  
**Execution Timestamp:** 2026-10-26T22:05:00+05:30  
**Project:** E-WITNESS High-Assurance Digital Evidence Management Platform  
**Target Ingestion Archive:** `https://www.kaggle.com/datasets/yash07yadav/project-data` ("Violence Detection - Combined")  
**Local Archive Directory:** `D:\PROJECT\E-WITTNESS\data\raw\Complete Dataset` (3,273 AVI files, 13,921,264,652 bytes)  
**Standardized Status Vocabulary:** `PASS` | `FAIL` | `BLOCKED` | `NOT RUN` | `APPROVED` | `RESTRICTED` | `UNVERIFIED`

---

## 1. Executive Summary & Legal Determination

A comprehensive provenance audit and primary legal source investigation was conducted across the composite Kaggle archive and six candidate violence-detection datasets (AIRTLab, VID, RWF-2000, Real Life Violence Situations, HockeyFight, MovieFights).

### Primary Finding & Legal Determination: **`BLOCKED`**
1. **Ineffective Aggregator Relicensing:** While the Kaggle web card declares `licenseName: "MIT"`, the archive aggregates footage from four external sources without copyright assignment or documented licensing authority. Under Berne Convention Art. 2, US Copyright Act 17 U.S.C. § 106, and Indian Copyright Act 1957 § 14, an aggregator cannot grant an open-source MIT license to third-party copyrighted works.
2. **Commercial Cinema Studio Copyright:** The `MovieFights` component consists of ripped clips from commercial Hollywood motion pictures uploaded to YouTube. These works remain under exclusive studio copyrights; third-party MIT relicensing is legally void.
3. **Academic Non-Commercial Restrictions:** Upstream datasets such as `RWF-2000` are strictly governed by SMIIP Lab's academic license prohibiting commercial exploitation, modification, and redistribution without written permission.
4. **Correction on Candidate Replacement Datasets:**
   - **AIRTLab:** Previous claims that AIRTLab is licensed under CC BY 4.0 were **incorrect**. The official GitHub repository contains no root `LICENSE` file; its README specifies an academic citation requirement only. It is **`RESTRICTED`** (research/educational only).
   - **VID Dataset:** Previous claims that the VID dataset on Harvard Dataverse is CC0 Public Domain were **incorrect**. The official Harvard Dataverse deposit is governed by **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**. It is **`RESTRICTED`** (non-commercial only).
5. **Overarching Legal Conclusion:** **No candidate dataset is currently commercially cleared or unreservedly approved for open-ended enterprise use without separate written clearance or strict non-commercial bounding.**
6. **Mandatory Action:** In accordance with E-WITNESS evidentiary integrity standards, **full model training remains formally `BLOCKED`**. Ingestion of any replacement dataset must pass through the fail-closed migration tool [`scripts/ingest_approved_dataset.py`](file:///D:/PROJECT/E-WITTNESS/scripts/ingest_approved_dataset.py).

---

## 2. Exhaustive Dataset Provenance Matrix

The following matrix documents all six evaluated datasets plus the composite Kaggle upload:

| Dataset | Original Publisher & Canonical Source | Exact License Text / Release Agreement & Date | Scope of License (Code vs Video Assets) | Expressly Permitted Uses | Attribution, Consent & Written Permission | Evidence Captured Locally & Final Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AIRTLab Automatic Violence Detection** | Artificial Intelligence & Robotics Lab (AIRTLab), Politecnico di Milano; Bianculli et al., Data in Brief 2020. GitHub: `airtlab/A-Dataset-for-Automatic-Violence-Detection-in-Videos` | No root `LICENSE` file in repo. README: *"Please cite the following paper if you use this dataset in your research: Bianculli et al., A dataset for automatic violence detection in videos, Data in Brief 2020."* (Retrieved 2026-10-26) | Research paper citation requirement only. No standard permissive open-source license applies to the video files. | **Commercial:** NO<br>**Training:** Research only<br>**Modify:** NO<br>**Redistribute:** NO<br>**Demonstrate:** Non-comm. | Mandatory paper citation. Consenting human subjects recorded under academic protocol. **Written permission required** for enterprise deployment. | Audited via GitHub repo & Data in Brief. Status: **`RESTRICTED`** |
| **VID Dataset (Harvard Dataverse)** | Mahi et al., Data in Brief 2024; Hosted on Harvard Dataverse (`doi:10.7910/DVN/CR4J0U`) | **CC BY-NC 4.0** (Creative Commons Attribution-NonCommercial 4.0 International). Terms: `https://creativecommons.org/licenses/by-nc/4.0/` (Retrieved 2026-10-26) | Applies to repository metadata and video files. NOT CC0. | **Commercial:** NO<br>**Training:** Non-comm. only<br>**Modify:** Yes (non-comm)<br>**Redistribute:** Yes (non-comm)<br>**Demonstrate:** Non-comm. | Non-commercial restriction strictly binding. Attribution required. Consenting actor recordings. **Written commercial license needed**. | Dataverse terms verified. Status: **`RESTRICTED`** |
| **RWF-2000 Surveillance Database** | Ming Cheng, Kunjing Cai, Ming Li; SMIIP Lab, Duke Kunshan University (ICPR 2020). GitHub: `mchengny/RWF2000-Video-Database-for-Violence-Detection` | Custom Academic Agreement: *"The RWF-2000 database is not allowed for commercial purposes without approval from the SMIIP Lab. Without approval from the SMIIP Lab, the RWF-2000 database is not allowed to be modified or redistributed."* (Retrieved 2026-10-26) | Applies to all video sequences and annotations in RWF-2000. | **Commercial:** NO<br>**Training:** Academic only<br>**Modify:** NO<br>**Redistribute:** NO<br>**Demonstrate:** NO | Strictly academic research. Modification and redistribution forbidden without SMIIP Lab consent. **Written permission mandatory**. | GitHub license text captured. Status: **`RESTRICTED`** |
| **Real Life Violence Situations** | Mohamed M. Soliman et al., Ain Shams University, Cairo (ICICIS 2019). Distributed via Kaggle & ResearchGate | No formal open license. Scraped from third-party YouTube street footage. Authors request paper citation only. (Retrieved 2026-10-26) | Third-party YouTube footage scraped without copyright holder clearance. | **Commercial:** NO<br>**Training:** Fair-use academic<br>**Modify:** NO<br>**Redistribute:** NO<br>**Demonstrate:** NO | YouTube Standard Terms of Service. Individual YouTube uploaders retain copyright. No subject consent recorded. **Clearance unverified**. | Scraped clips audit. Status: **`UNVERIFIED`** |
| **Hockey Fight Dataset** | Enrique Bermejo Nievas, Oscar Deniz Suarez et al., VISILAB, University of Castilla-La Mancha (CAIP 2011) | Academic fair-use distribution. Commercial television broadcast footage owned exclusively by National Hockey League (NHL). (Retrieved 2026-10-26) | NHL broadcast clips only. | **Commercial:** NO<br>**Training:** Benchmarking only<br>**Modify:** NO<br>**Redistribute:** NO<br>**Demonstrate:** NO | NHL broadcast copyright. Fair use for academic benchmarking only. Unusable for commercial product. **Written NHL license required**. | CAIP 2011 paper analysis. Status: **`RESTRICTED`** |
| **MovieFights** | Commercial Hollywood Cinema Studios (Warner Bros, Universal, Disney, Paramount, etc.) via YouTube excerpts | No license granted. Protected under US Copyright Act 17 U.S.C. § 106. (Retrieved 2026-10-26) | Studio feature motion pictures. | **Commercial:** NO<br>**Training:** NO<br>**Modify:** NO<br>**Redistribute:** NO<br>**Demonstrate:** NO | Exclusive studio copyrights. Derivative redistribution under open-source MIT is legally void. **Cannot be licensed**. | YouTube rips audit. Status: **`RESTRICTED`** / **`FAIL`** |
| **Combined Kaggle Package (`project-data`)** | Yash07Yadav (Kaggle User ID: `5764601`) | Declared "MIT" on Kaggle form metadata. No physical `LICENSE` file in download. (Retrieved 2026-10-26) | Aggregator metadata only. Inapplicable to third-party videos. | **Commercial:** Ineffective<br>**Training:** Blocked<br>**Modify:** Blocked<br>**Redistribute:** Blocked<br>**Demonstrate:** Blocked | Uploader lacks copyright assignment over constituent sources. **Full training prohibited**. | Kaggle REST API record. Status: **`BLOCKED`** |

---

## 3. Detailed Dataset Investigations & Corrections

### 3.1 Correction Regarding AIRTLab
- **Prior Claim:** "Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0)."
- **Audited Reality:** Inspection of the primary GitHub repository (`https://github.com/airtlab/A-Dataset-for-Automatic-Violence-Detection-in-Videos`) reveals **no `LICENSE` file** exists at the repository root or subfolders. The README contains only:
  > *"Please cite the following paper if you use this dataset in your research: Bianculli et al., A dataset for automatic violence detection in videos, Data in Brief 2020."*
- **Legal Scope:** While Data in Brief articles are published as open access, the accompanying video media assets hosted on external repositories are governed solely by the terms in that repository. AIRTLab grants research/educational citation permission, but does **not** grant CC BY 4.0 or commercial exploitation rights.
- **Corrected Status:** **`RESTRICTED`** (Non-commercial academic research only; requires explicit written commercial license for enterprise deployment).

### 3.2 Correction Regarding VID Dataset
- **Prior Claim:** "Licensed under Creative Commons Zero 1.0 Universal (CC0 1.0 Public Domain)."
- **Audited Reality:** Inspection of the canonical Harvard Dataverse record (`doi:10.7910/DVN/CR4J0U`) demonstrates that the dataset is distributed under **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**.
- **Legal Scope:** CC BY-NC 4.0 expressly prohibits commercial use:
  > *"NonCommercial — You may not use the material for commercial purposes."*
- Under E-WITNESS enterprise governance, commercial deployment or enterprise software integration without a separate commercial license is prohibited.
- **Corrected Status:** **`RESTRICTED`** (Non-commercial only; NOT CC0).

### 3.3 Detailed RWF-2000 Analysis
- **Canonical Repository:** `https://github.com/mchengny/RWF2000-Video-Database-for-Violence-Detection`
- **Authors:** Ming Cheng, Kunjing Cai, Ming Li (Duke Kunshan University / SMIIP Lab).
- **Official Licensing Clause:**
  > *"The RWF-2000 database is not allowed for commercial purposes without approval from the SMIIP Lab. Without approval from the SMIIP Lab, the RWF-2000 database is not allowed to be modified or redistributed."*
- **Assessment:** The Kaggle uploader modified RWF-2000 by clipping and restructuring into `Fight`/`NonFight` folders and relicensed it under MIT without SMIIP Lab approval. Relicensing is legally ineffective. Status: **`RESTRICTED`**.

### 3.4 Detailed MovieFights Analysis
- **Composition:** 223 high-definition clips (188 in `train`, 35 in `val`).
- **Source Material:** Excerpts from commercial Hollywood studio movies (e.g., Warner Bros, Sony Pictures, Universal).
- **Assessment:** Film studios hold exclusive rights under 17 U.S.C. § 106. Training an institutional machine learning model on pirated film clips uploaded to YouTube violates copyright compliance standards for law enforcement and judicial evidentiary platforms. Status: **`RESTRICTED` / `FAIL`**.

### 3.5 Detailed HockeyFight Analysis
- **Canonical Source:** VISILAB, Universidad de Castilla-La Mancha (Nievas et al., CAIP 2011).
- **Assessment:** The footage is owned by the National Hockey League (NHL) and broadcast networks. VISILAB distributed it under academic fair-use conventions. An open-source MIT license cannot be claimed over NHL broadcast footage. Status: **`RESTRICTED`**.

---

## 4. Safe Dataset Migration Tooling & Governance Architecture

To ensure that E-WITNESS can safely ingest any future approved replacement dataset without modifying raw source files or risking legal liability, a dedicated migration pipeline was implemented and verified:

### Ingestion Script: [`scripts/ingest_approved_dataset.py`](file:///D:/PROJECT/E-WITTNESS/scripts/ingest_approved_dataset.py)
1. **Fail-Closed Governance Validation:**
   - Validates that the input provenance metadata specifies `rights_status: "APPROVED"`.
   - Validates that `license_id` is an exact match in `backend.app.core.ai::APPROVED_DATASET_LICENSES`.
   - Rejects unverified, non-commercial, or unapproved licenses by raising `GovernanceError` and exiting with code 2.
2. **Read-Only Non-Destructive Scanning:**
   - Source dataset directory is accessed strictly read-only.
   - Computes SHA-256 digests for all video streams.
   - Quarantines 0-byte or corrupted video containers into `corrupted_files` without crashing.
3. **Deduplication & Cross-Split Leakage Prevention:**
   - Detects and purges duplicate files across partitions based on SHA-256 hashes.
   - Enforces disjoint partitions: zero hash collisions between `train`, `val`, and `test`.
   - Preserves source recording groups where available (`scene_prefix_verified`).
4. **Derived Artifacts Output:**
   - Outputs canonical `manifest.json` with deterministic manifest SHA-256.
   - Generates `ingestion_audit_report.json` and `INGESTION_SUMMARY.md`.
   - All derived files written atomically via `.tmp` file replacement.

---

## 5. Summary of Governance Gates for Full Training

Full 10-epoch training may proceed **only** when all of the following conditions are met:

1. **Dataset Clearance:** A replacement dataset with verified `APPROVED` rights status and an approved SPDX license (`CC-BY-4.0`, `MIT`, `Apache-2.0`, `CC0-1.0`) is supplied.
2. **Provenance Record:** A completed `provenance.json` is audited and signed by the engineering and legal governance leads.
3. **Migration Execution:** `scripts/ingest_approved_dataset.py` successfully generates `manifest.json` with zero cross-split collisions.
4. **Civil-Rights Invariant:** `BIOMETRIC_MATCHING_ENABLED = False` remains strictly enforced.

*Report certified by Antigravity Senior Full-Stack & ML Systems Engineering.*
