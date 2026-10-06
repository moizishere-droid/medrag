"""The shared curated topic list used by ingestion and the public interface."""
TOPICS = [
    "diabetes", "hypertension", "obesity", "hyperlipidemia",
    "asthma", "copd", "pneumonia", "tuberculosis",
    "coronary artery disease", "heart failure", "stroke", "arrhythmia",
    "malaria", "dengue fever", "hiv aids", "hepatitis b", "covid-19", "typhoid",
    "depression", "anxiety disorder",
    "peptic ulcer disease", "irritable bowel syndrome", "hepatitis c",
    "osteoarthritis", "rheumatoid arthritis", "osteoporosis",
    "hypothyroidism", "hyperthyroidism",
    "epilepsy", "migraine", "parkinson's disease",
    "chronic kidney disease", "breast cancer", "lung cancer",
    "anemia in pregnancy", "malnutrition",
]


def topic_label(topic):
    return {"copd": "COPD", "hiv aids": "HIV/AIDS", "covid-19": "COVID-19"}.get(topic, topic.capitalize())
