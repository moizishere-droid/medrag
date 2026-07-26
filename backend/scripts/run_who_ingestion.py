"""
Run WHO guideline ingestion for all topics with a real, dedicated WHO guideline.

Run from the backend/ folder:
    cd backend
    python scripts/run_who_ingestion.py

Note: 12 of the 36 project topics (osteoarthritis, rheumatoid arthritis,
osteoporosis, chronic kidney disease, lung cancer, peptic ulcer disease,
irritable bowel syndrome, arrhythmia, hypothyroidism, hyperthyroidism,
migraine, Parkinson's disease) have no dedicated WHO guideline and are
intentionally absent from this script's topic map.
"""

import sys
import os
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from medrag.ingestion.who_client import fetch_who_guideline, BROWSER_HEADERS
from medrag.ingestion.storage import save_guideline

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("medrag.ingestion")

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "who"))

# topic -> (source document URL, document title)
# Several topics intentionally share the same source document
# (e.g. asthma/copd via the PEN package; coronary artery disease/heart
# failure/stroke/hyperlipidemia via the CVD risk guideline; depression/
# anxiety disorder/epilepsy via mhGAP).
TOPIC_DOCS = {
    "tuberculosis": (
        "https://iris.who.int/server/api/core/bitstreams/cf34aa08-c5d4-4b64-85cd-2ec1e6b14d91/content",
        "WHO consolidated guidelines on tuberculosis: Module 4 Treatment",
    ),
    "hypertension": (
        "https://iris.who.int/server/api/core/bitstreams/f062769d-f075-4a00-87af-0a2106e0bd04/content",
        "Guideline for the pharmacological treatment of hypertension in adults",
    ),
    "diabetes": (
        "https://cdn.who.int/media/docs/default-source/ncds/ncd-surveillance/guidance-on-global-monitoring-for-diabetes.pdf",
        "Guidance on global monitoring for diabetes prevention and control",
    ),
    "obesity": (
        "https://cdn.who.int/media/docs/default-source/obesity/who-discussion-paper-on-obesity---final190821.pdf",
        "WHO discussion paper on obesity",
    ),
    "asthma": (
        "https://iris.who.int/server/api/core/bitstreams/b9f09202-a320-4c07-ba2c-afe0d1186339/content",
        "WHO package of essential noncommunicable (PEN) disease interventions",
    ),
    "copd": (
        "https://iris.who.int/server/api/core/bitstreams/b9f09202-a320-4c07-ba2c-afe0d1186339/content",
        "WHO package of essential noncommunicable (PEN) disease interventions",
    ),
    "coronary artery disease": (
        "https://iris.who.int/server/api/core/bitstreams/f106282d-01ad-4978-9a61-27fb1a8c305d/content",
        "Prevention of cardiovascular disease: guidelines for assessment and management of total cardiovascular risk",
    ),
    "heart failure": (
        "https://iris.who.int/server/api/core/bitstreams/f106282d-01ad-4978-9a61-27fb1a8c305d/content",
        "Prevention of cardiovascular disease: guidelines for assessment and management of total cardiovascular risk",
    ),
    "stroke": (
        "https://iris.who.int/server/api/core/bitstreams/f106282d-01ad-4978-9a61-27fb1a8c305d/content",
        "Prevention of cardiovascular disease: guidelines for assessment and management of total cardiovascular risk",
    ),
    "hyperlipidemia": (
        "https://iris.who.int/server/api/core/bitstreams/f106282d-01ad-4978-9a61-27fb1a8c305d/content",
        "Prevention of cardiovascular disease: guidelines for assessment and management of total cardiovascular risk",
    ),
    "pneumonia": (
        "https://iris.who.int/server/api/core/bitstreams/38cf9b2a-5d7d-49de-a27b-46d5ac4fc387/content",
        "Revised WHO classification and treatment of childhood pneumonia at health facilities",
    ),
    "covid-19": (
        "https://iris.who.int/server/api/core/bitstreams/54fd5754-5ae5-4af1-bc1b-f15960301f17/content",
        "Clinical management of COVID-19: living guideline",
    ),
    "malaria": (
        "https://iris.who.int/server/api/core/bitstreams/8fa903e7-5502-4c33-a300-7a3f3469bfab/content",
        "WHO guidelines for malaria",
    ),
    "hiv aids": (
        "https://iris.who.int/server/api/core/bitstreams/15bfbf7f-9dc6-44fe-8dc5-1beb7be8848b/content",
        "WHO updated recommendations on HIV clinical management",
    ),
    "hepatitis b": (
        "https://iris.who.int/server/api/core/bitstreams/51bfba1f-fbbe-4ae3-a950-48cf39601916/content",
        "Guidelines for the prevention, care and treatment of persons with chronic hepatitis B infection",
    ),
    "hepatitis c": (
        "https://iris.who.int/server/api/core/bitstreams/8bad8f1b-84c4-4abd-9653-99dcc807e6ff/content",
        "Guidelines for the care and treatment of persons diagnosed with chronic hepatitis C virus infection",
    ),
    "dengue fever": (
        "https://iris.who.int/server/api/core/bitstreams/825eb07b-b372-4527-ac2f-fe6e8201c1c1/content",
        "Handbook for clinical management of dengue",
    ),
    "typhoid": (
        "https://iris.who.int/server/api/core/bitstreams/ebae84fc-9d27-420a-9e6f-41cb85873832/content",
        "Background document: the diagnosis, treatment and prevention of typhoid fever",
    ),
    "depression": (
        "https://iris.who.int/server/api/core/bitstreams/6b9d19fe-b732-4065-bd2f-9736f4061a7e/content",
        "mhGAP guideline for mental, neurological and substance use disorders",
    ),
    "anxiety disorder": (
        "https://iris.who.int/server/api/core/bitstreams/6b9d19fe-b732-4065-bd2f-9736f4061a7e/content",
        "mhGAP guideline for mental, neurological and substance use disorders",
    ),
    "epilepsy": (
        "https://iris.who.int/server/api/core/bitstreams/6b9d19fe-b732-4065-bd2f-9736f4061a7e/content",
        "mhGAP guideline for mental, neurological and substance use disorders",
    ),
    "malnutrition": (
        "https://iris.who.int/server/api/core/bitstreams/0c5e1662-a300-4827-90fa-962ac21360dd/content",
        "Guideline: updates on the management of severe acute malnutrition in infants and children",
    ),
    "anemia in pregnancy": (
        "https://iris.who.int/server/api/core/bitstreams/f9f74397-1440-478d-a63c-26f29a01552f/content",
        "WHO guideline on anaemia",
    ),
    "breast cancer": (
        "https://iris.who.int/server/api/core/bitstreams/efbe53e5-9354-482d-8c75-94cc7a1110b4/content",
        "WHO position paper on mammography screening",
    ),
}


def main():
    results = []
    for topic, (url, title) in TOPIC_DOCS.items():
        try:
            guideline = fetch_who_guideline(topic=topic, url=url, title=title, headers=BROWSER_HEADERS)
            save_guideline(guideline, output_dir=OUTPUT_DIR)
            logger.info(f"{topic}: saved ({guideline.num_pages} pages, {len(guideline.full_text)} chars)")
            results.append({"topic": topic, "status": "success"})
        except Exception as e:
            logger.error(f"{topic}: FAILED - {e}")
            results.append({"topic": topic, "status": "failed", "error": str(e)})
        time.sleep(1)  # be polite to WHO's servers between downloads

    success_count = sum(1 for r in results if r["status"] == "success")
    logger.info(f"=== DONE === {success_count}/{len(results)} succeeded")


if __name__ == "__main__":
    main()