"""
Fetch real NADAC (National Average Drug Acquisition Cost) prices from CMS.
Downloads the latest NADAC CSV file from the official CMS download server.
NADAC represents the average invoice price pharmacies pay for medications.

This version converts prices to dollars per gram ($/g) for oral solid medications
and excludes medications without NADAC data.
"""

import csv
import io
import json
import re
import requests
from datetime import datetime

# Official NADAC CSV download URL (updated weekly by CMS)
# This URL is obtained from the DKAN metastore API
NADAC_CSV_URL = "https://download.medicaid.gov/data/nadac-national-average-drug-acquisition-cost-latest.csv"

# Medicine names mapped to their generic ingredient names for NADAC search
# Format: "Display Name": {"search": ["search_term1", ...], "strength": typical_strength_in_mg}
# Strength is used to convert per-unit NADAC price to per-gram price
MEDICINE_SEARCH_TERMS = {
    # Pain relievers & fever reducers (OTC)
    "Paracetamol (Acetaminophen)": {"search": ["acetaminophen"], "strength": 500, "symptoms": ["headache", "fever", "pain relief", "body ache", "toothache", "back pain", "muscle pain", "cold symptoms", "flu symptoms", "mild pain"]},
    "Ibuprofen": {"search": ["ibuprofen"], "strength": 200, "symptoms": ["headache", "fever", "inflammation", "pain relief", "swelling", "arthritis", "back pain", "muscle pain", "toothache", "menstrual cramps", "joint pain"]},
    "Aspirin": {"search": ["aspirin"], "strength": 325, "symptoms": ["headache", "fever", "pain relief", "inflammation", "heart health", "blood thinner", "chest pain", "stroke prevention"]},
    "Naproxen": {"search": ["naproxen"], "strength": 220, "symptoms": ["headache", "inflammation", "pain relief", "arthritis", "back pain", "muscle pain", "joint pain", "menstrual cramps", "swelling"]},
    "Aspirin Low Dose (81mg)": {"search": ["aspirin 81"], "strength": 81, "symptoms": ["heart health", "blood thinner", "stroke prevention", "cardiovascular", "clot prevention"]},

    # Prescription pain medications
    "Hydrocodone/Acetaminophen": {"search": ["hydrocodone acetaminophen"], "strength": 5, "symptoms": ["severe pain", "post-surgery pain", "injury pain", "chronic pain"]},
    "Oxycodone": {"search": ["oxycodone"], "strength": 5, "symptoms": ["severe pain", "post-surgery pain", "cancer pain", "chronic pain"]},
    "Tramadol": {"search": ["tramadol"], "strength": 50, "symptoms": ["moderate pain", "chronic pain", "back pain", "arthritis pain"]},
    "Gabapentin": {"search": ["gabapentin"], "strength": 300, "symptoms": ["nerve pain", "seizures", "epilepsy", "neuropathy", "restless leg syndrome", "burning pain"]},
    "Pregabalin": {"search": ["pregabalin"], "strength": 75, "symptoms": ["nerve pain", "seizures", "fibromyalgia", "neuropathy", "anxiety", "back pain"]},
    "Prednisone": {"search": ["prednisone"], "strength": 10, "symptoms": ["inflammation", "allergies", "asthma", "arthritis", "autoimmune", "swelling", "rheumatoid arthritis"]},
    "Prednisolone": {"search": ["prednisolone"], "strength": 5, "symptoms": ["inflammation", "allergies", "asthma", "arthritis", "autoimmune", "swelling"]},
    "Dexamethasone": {"search": ["dexamethasone"], "strength": 4, "symptoms": ["inflammation", "brain swelling", "cancer", "allergies", "asthma", "autoimmune"]},
    "Meloxicam": {"search": ["meloxicam"], "strength": 15, "symptoms": ["arthritis", "joint pain", "inflammation", "osteoarthritis", "rheumatoid arthritis", "back pain"]},
    "Celecoxib": {"search": ["celecoxib"], "strength": 200, "symptoms": ["arthritis", "joint pain", "inflammation", "osteoarthritis", "back pain", "menstrual cramps"]},
    "Diclofenac": {"search": ["diclofenac"], "strength": 25, "symptoms": ["arthritis", "pain relief", "inflammation", "swelling", "joint pain", "back pain", "osteoarthritis"]},
    "Indomethacin": {"search": ["indomethacin"], "strength": 25, "symptoms": ["gout", "arthritis", "inflammation", "migraine", "back pain", "joint pain"]},
    "Cyclobenzaprine": {"search": ["cyclobenzaprine"], "strength": 10, "symptoms": ["muscle spasms", "muscle pain", "back pain", "neck pain", "muscle stiffness"]},
    "Tizanidine": {"search": ["tizanidine"], "strength": 2, "symptoms": ["muscle spasms", "muscle stiffness", "multiple sclerosis", "back pain", "spasticity"]},
    "Methocarbamol": {"search": ["methocarbamol"], "strength": 750, "symptoms": ["muscle spasms", "muscle pain", "back pain", "muscle stiffness", "injury"]},

    # Antibiotics
    "Amoxicillin": {"search": ["amoxicillin"], "strength": 500, "symptoms": ["bacterial infection", "ear infection", "throat infection", "urinary tract infection", "pneumonia", "skin infection"]},
    "Amoxicillin/Clavulanate": {"search": ["amoxicillin clavulanate"], "strength": 500, "symptoms": ["bacterial infection", "sinus infection", "ear infection", "pneumonia", "skin infection", "UTI"]},
    "Azithromycin": {"search": ["azithromycin"], "strength": 250, "symptoms": ["bacterial infection", "ear infection", "sinus infection", "pneumonia", "throat infection", "skin infection"]},
    "Ciprofloxacin": {"search": ["ciprofloxacin"], "strength": 250, "symptoms": ["bacterial infection", "UTI", "urinary tract infection", "kidney infection", "skin infection", "respiratory infection"]},
    "Doxycycline": {"search": ["doxycycline"], "strength": 100, "symptoms": ["bacterial infection", "acne", "Lyme disease", "respiratory infection", "UTI", "skin infection", "malaria prevention"]},
    "Levofloxacin": {"search": ["levofloxacin"], "strength": 250, "symptoms": ["bacterial infection", "pneumonia", "sinus infection", "UTI", "skin infection", "respiratory infection"]},
    "Metronidazole": {"search": ["metronidazole"], "strength": 250, "symptoms": ["bacterial infection", "parasitic infection", "dental infection", "vaginal infection", "C. diff", "anaerobic infection"]},
    "Cephalexin": {"search": ["cephalexin"], "strength": 250, "symptoms": ["bacterial infection", "skin infection", "urinary tract infection", "bone infection", "throat infection"]},
    "Trimethoprim/Sulfamethoxazole": {"search": ["trimethoprim sulfamethoxazole"], "strength": 80, "symptoms": ["UTI", "urinary tract infection", "ear infection", "skin infection", "pneumocystis", "bacterial infection"]},
    "Clindamycin": {"search": ["clindamycin"], "strength": 150, "symptoms": ["bacterial infection", "dental infection", "skin infection", "bone infection", "anaerobic infection"]},
    "Nitrofurantoin": {"search": ["nitrofurantoin"], "strength": 50, "symptoms": ["UTI", "urinary tract infection", "bladder infection", "urinary infection"]},
    "Fluconazole": {"search": ["fluconazole"], "strength": 100, "symptoms": ["yeast infection", "fungal infection", "thrush", "vaginal yeast", "candida"]},
    "Valacyclovir": {"search": ["valacyclovir"], "strength": 500, "symptoms": ["cold sores", "shingles", "herpes", "genital herpes", "viral infection"]},
    "Acyclovir": {"search": ["acyclovir"], "strength": 200, "symptoms": ["cold sores", "shingles", "herpes", "viral infection", "chickenpox"]},
    "Erythromycin": {"search": ["erythromycin"], "strength": 250, "symptoms": ["bacterial infection", "respiratory infection", "skin infection", "acne", "throat infection"]},
    "Penicillin VK": {"search": ["penicillin vk"], "strength": 250, "symptoms": ["bacterial infection", "strep throat", "skin infection", "dental infection"]},
    "Tetracycline": {"search": ["tetracycline"], "strength": 250, "symptoms": ["bacterial infection", "acne", "respiratory infection", "skin infection", "H. pylori"]},
    "Minocycline": {"search": ["minocycline"], "strength": 50, "symptoms": ["acne", "bacterial infection", "skin infection", "rheumatoid arthritis"]},

    # Blood pressure & heart medications
    "Lisinopril": {"search": ["lisinopril"], "strength": 10, "symptoms": ["high blood pressure", "hypertension", "heart failure", "after heart attack", "kidney protection"]},
    "Amlodipine": {"search": ["amlodipine"], "strength": 5, "symptoms": ["high blood pressure", "hypertension", "chest pain", "angina", "heart health"]},
    "Metoprolol": {"search": ["metoprolol"], "strength": 50, "symptoms": ["high blood pressure", "chest pain", "heart failure", "angina", "irregular heartbeat", "migraine prevention"]},
    "Losartan": {"search": ["losartan"], "strength": 50, "symptoms": ["high blood pressure", "hypertension", "kidney protection", "diabetic nephropathy", "stroke prevention"]},
    "Hydrochlorothiazide": {"search": ["hydrochlorothiazide"], "strength": 25, "symptoms": ["high blood pressure", "hypertension", "fluid retention", "edema", "swelling"]},
    "Atenolol": {"search": ["atenolol"], "strength": 50, "symptoms": ["high blood pressure", "chest pain", "angina", "irregular heartbeat", "heart failure"]},
    "Carvedilol": {"search": ["carvedilol"], "strength": 12.5, "symptoms": ["heart failure", "high blood pressure", "hypertension", "after heart attack"]},
    "Valsartan": {"search": ["valsartan"], "strength": 80, "symptoms": ["high blood pressure", "hypertension", "heart failure", "after heart attack", "stroke prevention"]},
    "Furosemide": {"search": ["furosemide"], "strength": 20, "symptoms": ["fluid retention", "edema", "heart failure", "liver disease", "kidney disease", "high blood pressure", "swelling"]},
    "Spironolactone": {"search": ["spironolactone"], "strength": 25, "symptoms": ["high blood pressure", "heart failure", "fluid retention", "edema", "acne", "hirsutism"]},
    "Clonidine": {"search": ["clonidine"], "strength": 0.1, "symptoms": ["high blood pressure", "ADHD", "anxiety", "hot flashes", "migraine prevention", "restlessness"]},
    "Diltiazem": {"search": ["diltiazem"], "strength": 120, "symptoms": ["high blood pressure", "chest pain", "angina", "irregular heartbeat", "atrial fibrillation"]},
    "Verapamil": {"search": ["verapamil"], "strength": 120, "symptoms": ["high blood pressure", "chest pain", "angina", "irregular heartbeat", "migraine prevention"]},
    "Warfarin": {"search": ["warfarin"], "strength": 5, "symptoms": ["blood thinner", "clot prevention", "atrial fibrillation", "stroke prevention", "deep vein thrombosis"]},
    "Clopidogrel": {"search": ["clopidogrel"], "strength": 75, "symptoms": ["blood thinner", "clot prevention", "after heart attack", "stroke prevention", "stent"]},
    "Digoxin": {"search": ["digoxin"], "strength": 0.125, "symptoms": ["heart failure", "atrial fibrillation", "irregular heartbeat", "slow heartbeat"]},
    "Apixaban": {"search": ["apixaban"], "strength": 5, "symptoms": ["blood thinner", "clot prevention", "atrial fibrillation", "stroke prevention", "DVT"]},
    "Rivaroxaban": {"search": ["rivaroxaban"], "strength": 10, "symptoms": ["blood thinner", "clot prevention", "atrial fibrillation", "stroke prevention", "DVT"]},
    "Losartan/HCTZ": {"search": ["losartan hydrochlorothiazide"], "strength": 50, "symptoms": ["high blood pressure", "hypertension", "kidney protection"]},
    "Lisinopril/HCTZ": {"search": ["lisinopril hydrochlorothiazide"], "strength": 10, "symptoms": ["high blood pressure", "hypertension", "fluid retention"]},
    "Amlodipine/Valsartan": {"search": ["amlodipine valsartan"], "strength": 5, "symptoms": ["high blood pressure", "hypertension", "heart failure"]},

    # Cholesterol medications
    "Atorvastatin": {"search": ["atorvastatin"], "strength": 20, "symptoms": ["high cholesterol", "cholesterol", "heart health", "stroke prevention", "cardiovascular"]},
    "Simvastatin": {"search": ["simvastatin"], "strength": 20, "symptoms": ["high cholesterol", "cholesterol", "heart health", "cardiovascular"]},
    "Rosuvastatin": {"search": ["rosuvastatin"], "strength": 10, "symptoms": ["high cholesterol", "cholesterol", "heart health", "stroke prevention"]},
    "Pravastatin": {"search": ["pravastatin"], "strength": 20, "symptoms": ["high cholesterol", "cholesterol", "heart health", "cardiovascular"]},
    "Ezetimibe": {"search": ["ezetimibe"], "strength": 10, "symptoms": ["high cholesterol", "cholesterol", "heart health"]},
    "Fenofibrate": {"search": ["fenofibrate"], "strength": 145, "symptoms": ["high triglycerides", "triglycerides", "cholesterol", "lipid disorder"]},
    "Gemfibrozil": {"search": ["gemfibrozil"], "strength": 600, "symptoms": ["high triglycerides", "triglycerides", "cholesterol", "lipid disorder"]},
    "Ezetimibe/Simvastatin": {"search": ["ezetimibe simvastatin"], "strength": 10, "symptoms": ["high cholesterol", "cholesterol", "heart health"]},

    # Diabetes medications
    "Metformin": {"search": ["metformin"], "strength": 500, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "insulin resistance", "PCOS", "high blood sugar"]},
    "Glipizide": {"search": ["glipizide"], "strength": 5, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "high blood sugar"]},
    "Glyburide": {"search": ["glyburide"], "strength": 5, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "high blood sugar"]},
    "Pioglitazone": {"search": ["pioglitazone"], "strength": 30, "symptoms": ["diabetes", "type 2 diabetes", "insulin resistance", "blood sugar"]},
    "Sitagliptin": {"search": ["sitagliptin"], "strength": 10, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "high blood sugar"]},
    "Empagliflozin": {"search": ["empagliflozin"], "strength": 10, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "heart failure", "kidney protection"]},
    "Dapagliflozin": {"search": ["dapagliflozin"], "strength": 5, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "heart failure", "kidney protection"]},
    "Glimepiride": {"search": ["glimepiride"], "strength": 2, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "high blood sugar"]},
    "Canagliflozin": {"search": ["canagliflozin"], "strength": 100, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "kidney protection"]},
    "Metformin/Sitagliptin": {"search": ["metformin sitagliptin"], "strength": 500, "symptoms": ["diabetes", "type 2 diabetes", "blood sugar", "high blood sugar"]},

    # Allergy & cold medications
    "Cetirizine": {"search": ["cetirizine"], "strength": 10, "symptoms": ["allergies", "hay fever", "sneezing", "runny nose", "itchy eyes", "hives", "allergic rhinitis"]},
    "Loratadine": {"search": ["loratadine"], "strength": 10, "symptoms": ["allergies", "hay fever", "sneezing", "runny nose", "itchy eyes", "allergic rhinitis"]},
    "Fexofenadine": {"search": ["fexofenadine"], "strength": 60, "symptoms": ["allergies", "hay fever", "sneezing", "runny nose", "itchy eyes", "allergic rhinitis"]},
    "Diphenhydramine": {"search": ["diphenhydramine"], "strength": 25, "symptoms": ["allergies", "sleeping aid", "itching", "runny nose", "sneezing", "insomnia", "motion sickness"]},
    "Chlorpheniramine": {"search": ["chlorpheniramine"], "strength": 4, "symptoms": ["allergies", "runny nose", "sneezing", "hay fever", "cold symptoms"]},
    "Montelukast": {"search": ["montelukast"], "strength": 10, "symptoms": ["asthma", "allergies", "hay fever", "allergic rhinitis", "breathing"]},
    "Pseudoephedrine": {"search": ["pseudoephedrine"], "strength": 30, "symptoms": ["nasal congestion", "stuffy nose", "sinus pressure", "cold symptoms", "allergies"]},
    "Guaifenesin": {"search": ["guaifenesin"], "strength": 600, "symptoms": ["cough", "mucus", "chest congestion", "cold symptoms", "expectorant"]},
    "Dextromethorphan": {"search": ["dextromethorphan"], "strength": 15, "symptoms": ["cough", "dry cough", "cold symptoms", "cough suppressant"]},
    "Olopatadine": {"search": ["olopatadine"], "strength": 0.5, "symptoms": ["allergies", "itchy eyes", "eye allergies", "allergic conjunctivitis", "red eyes"]},
    "Azelastine": {"search": ["azelastine"], "strength": 0.125, "symptoms": ["allergies", "runny nose", "sneezing", "hay fever", "allergic rhinitis", "itchy nose"]},

    # Respiratory medications
    "Albuterol Inhaler": {"search": ["albuterol inhal"], "strength": 90, "symptoms": ["asthma", "breathing", "wheezing", "shortness of breath", "COPD", "bronchospasm"]},
    "Fluticasone": {"search": ["fluticasone"], "strength": 0.05, "symptoms": ["asthma", "allergies", "nasal congestion", "hay fever", "breathing", "inflammation"]},
    "Budesonide": {"search": ["budesonide"], "strength": 0.18, "symptoms": ["asthma", "breathing", "inflammation", "COPD", "wheezing"]},
    "Tiotropium": {"search": ["tiotropium"], "strength": 0.01875, "symptoms": ["COPD", "emphysema", "chronic bronchitis", "breathing", "shortness of breath"]},
    "Ipratropium": {"search": ["ipratropium"], "strength": 0.02, "symptoms": ["COPD", "bronchospasm", "breathing", "wheezing", "chronic bronchitis"]},
    "Salmeterol/Fluticasone": {"search": ["salmeterol fluticasone"], "strength": 0.05, "symptoms": ["asthma", "breathing", "wheezing", "COPD", "long-term asthma"]},
    "Formoterol/Budesonide": {"search": ["formoterol budesonide"], "strength": 0.0045, "symptoms": ["asthma", "COPD", "breathing", "wheezing", "shortness of breath"]},
    "Guaifenesin/Dextromethorphan": {"search": ["guaifenesin dextromethorphan"], "strength": 200, "symptoms": ["cough", "mucus", "chest congestion", "cold symptoms", "cough with mucus"]},

    # Stomach & digestive medications
    "Omeprazole": {"search": ["omeprazole"], "strength": 20, "symptoms": ["acid reflux", "heartburn", "GERD", "stomach ulcer", "indigestion", "stomach acid"]},
    "Esomeprazole": {"search": ["esomeprazole"], "strength": 20, "symptoms": ["acid reflux", "heartburn", "GERD", "stomach ulcer", "indigestion"]},
    "Lansoprazole": {"search": ["lansoprazole"], "strength": 30, "symptoms": ["acid reflux", "heartburn", "stomach ulcer", "GERD", "indigestion"]},
    "Pantoprazole": {"search": ["pantoprazole"], "strength": 40, "symptoms": ["acid reflux", "heartburn", "GERD", "stomach ulcer", "indigestion"]},
    "Famotidine": {"search": ["famotidine"], "strength": 20, "symptoms": ["heartburn", "acid reflux", "stomach ulcer", "indigestion", "stomach acid"]},
    "Cimetidine": {"search": ["cimetidine"], "strength": 300, "symptoms": ["heartburn", "stomach ulcer", "acid reflux", "indigestion"]},
    "Metoclopramide": {"search": ["metoclopramide"], "strength": 10, "symptoms": ["nausea", "vomiting", "gastroparesis", "acid reflux", "stomach emptying"]},
    "Ondansetron": {"search": ["ondansetron"], "strength": 4, "symptoms": ["nausea", "vomiting", "chemotherapy nausea", "post-surgery nausea"]},
    "Promethazine": {"search": ["promethazine"], "strength": 12.5, "symptoms": ["nausea", "vomiting", "motion sickness", "allergies", "sleeping aid", "itching"]},
    "Loperamide": {"search": ["loperamide"], "strength": 2, "symptoms": ["diarrhea", "upset stomach", "loose stools", "traveler's diarrhea"]},
    "Docusate": {"search": ["docusate"], "strength": 100, "symptoms": ["constipation", "stool softener", "bowel movement", "hard stools"]},
    "Senna": {"search": ["senna"], "strength": 8.6, "symptoms": ["constipation", "bowel movement", "laxative", "irregular bowel"]},
    "Polyethylene Glycol": {"search": ["polyethylene glycol"], "strength": 10, "symptoms": ["constipation", "laxative", "bowel movement", "irregular bowel"]},
    "Bisacodyl": {"search": ["bisacodyl"], "strength": 5, "symptoms": ["constipation", "laxative", "bowel movement", "irregular bowel"]},
    "Simethicone": {"search": ["simethicone"], "strength": 80, "symptoms": ["gas", "bloating", "indigestion", "stomach discomfort", "belching"]},
    "Mesalamine": {"search": ["mesalamine"], "strength": 400, "symptoms": ["ulcerative colitis", "Crohn's disease", "IBD", "inflammatory bowel disease", "diarrhea"]},
    "Prochlorperazine": {"search": ["prochlorperazine"], "strength": 5, "symptoms": ["nausea", "vomiting", "migraine", "headache"]},

    # Mental health & neurological medications
    "Amitriptyline": {"search": ["amitriptyline"], "strength": 10, "symptoms": ["depression", "migraine prevention", "nerve pain", "chronic pain", "insomnia", "anxiety"]},
    "Nortriptyline": {"search": ["nortriptyline"], "strength": 10, "symptoms": ["depression", "migraine prevention", "nerve pain", "chronic pain"]},
    "Duloxetine": {"search": ["duloxetine"], "strength": 30, "symptoms": ["depression", "anxiety", "nerve pain", "fibromyalgia", "chronic pain", "urinary incontinence"]},
    "Venlafaxine": {"search": ["venlafaxine"], "strength": 37.5, "symptoms": ["depression", "anxiety", "panic disorder", "social anxiety", "generalized anxiety"]},
    "Bupropion": {"search": ["bupropion"], "strength": 100, "symptoms": ["depression", "smoking cessation", "ADHD", "seasonal affective disorder", "low energy"]},
    "Trazodone": {"search": ["trazodone"], "strength": 50, "symptoms": ["depression", "insomnia", "sleeping aid", "anxiety", "sleep disorder"]},
    "Mirtazapine": {"search": ["mirtazapine"], "strength": 15, "symptoms": ["depression", "insomnia", "anxiety", "appetite loss", "sleep disorder"]},
    "Fluoxetine": {"search": ["fluoxetine"], "strength": 20, "symptoms": ["depression", "anxiety", "OCD", "panic disorder", "eating disorder", "bulimia"]},
    "Sertraline": {"search": ["sertraline"], "strength": 50, "symptoms": ["depression", "anxiety", "OCD", "PTSD", "panic disorder", "social anxiety"]},
    "Escitalopram": {"search": ["escitalopram"], "strength": 10, "symptoms": ["depression", "anxiety", "generalized anxiety", "panic disorder"]},
    "Citalopram": {"search": ["citalopram"], "strength": 20, "symptoms": ["depression", "anxiety", "generalized anxiety", "mood disorder"]},
    "Paroxetine": {"search": ["paroxetine"], "strength": 20, "symptoms": ["depression", "anxiety", "OCD", "PTSD", "panic disorder", "social anxiety"]},
    "Alprazolam": {"search": ["alprazolam"], "strength": 0.25, "symptoms": ["anxiety", "panic disorder", "panic attacks", "generalized anxiety"]},
    "Lorazepam": {"search": ["lorazepam"], "strength": 0.5, "symptoms": ["anxiety", "panic attacks", "insomnia", "seizures", "sedation"]},
    "Clonazepam": {"search": ["clonazepam"], "strength": 0.5, "symptoms": ["anxiety", "panic disorder", "seizures", "epilepsy", "panic attacks"]},
    "Diazepam": {"search": ["diazepam"], "strength": 5, "symptoms": ["anxiety", "muscle spasms", "seizures", "alcohol withdrawal", "panic attacks"]},
    "Zolpidem": {"search": ["zolpidem"], "strength": 5, "symptoms": ["insomnia", "sleeping aid", "sleep disorder", "trouble sleeping"]},
    "Levothyroxine": {"search": ["levothyroxine"], "strength": 0.05, "symptoms": ["hypothyroidism", "thyroid", "low thyroid", "fatigue", "weight gain"]},
    "Methimazole": {"search": ["methimazole"], "strength": 5, "symptoms": ["hyperthyroidism", "thyroid", "overactive thyroid", "Graves disease"]},
    "Lithium": {"search": ["lithium"], "strength": 300, "symptoms": ["bipolar disorder", "mood swings", "mania", "depression", "mood stabilizer"]},
    "Valproic Acid": {"search": ["valproic acid"], "strength": 250, "symptoms": ["seizures", "epilepsy", "bipolar disorder", "migraine prevention", "mood stabilizer"]},
    "Lamotrigine": {"search": ["lamotrigine"], "strength": 100, "symptoms": ["seizures", "epilepsy", "bipolar disorder", "mood stabilizer"]},
    "Carbamazepine": {"search": ["carbamazepine"], "strength": 200, "symptoms": ["seizures", "epilepsy", "trigeminal neuralgia", "bipolar disorder", "nerve pain"]},
    "Phenytoin": {"search": ["phenytoin"], "strength": 100, "symptoms": ["seizures", "epilepsy", "seizure prevention"]},
    "Topiramate": {"search": ["topiramate"], "strength": 100, "symptoms": ["seizures", "epilepsy", "migraine prevention", "weight loss"]},
    "Levetiracetam": {"search": ["levetiracetam"], "strength": 500, "symptoms": ["seizures", "epilepsy", "seizure prevention"]},
    "Risperidone": {"search": ["risperidone"], "strength": 1, "symptoms": ["schizophrenia", "bipolar disorder", "irritability", "psychosis", "autism irritability"]},
    "Quetiapine": {"search": ["quetiapine"], "strength": 100, "symptoms": ["schizophrenia", "bipolar disorder", "depression", "psychosis", "insomnia"]},
    "Olanzapine": {"search": ["olanzapine"], "strength": 5, "symptoms": ["schizophrenia", "bipolar disorder", "psychosis", "mania", "depression"]},
    "Aripiprazole": {"search": ["aripiprazole"], "strength": 10, "symptoms": ["schizophrenia", "bipolar disorder", "depression", "irritability", "psychosis"]},
    "Haloperidol": {"search": ["haloperidol"], "strength": 1, "symptoms": ["schizophrenia", "psychosis", "tourette syndrome", "mania", "delirium"]},
    "Methylphenidate": {"search": ["methylphenidate"], "strength": 10, "symptoms": ["ADHD", "attention deficit", "narcolepsy", "focus", "concentration"]},
    "Amphetamine/Dextroamphetamine": {"search": ["amphetamine dextroamphetamine"], "strength": 5, "symptoms": ["ADHD", "attention deficit", "narcolepsy", "focus", "concentration"]},
    "Atomoxetine": {"search": ["atomoxetine"], "strength": 20, "symptoms": ["ADHD", "attention deficit", "focus", "concentration", "impulsivity"]},
    "Clozapine": {"search": ["clozapine"], "strength": 25, "symptoms": ["schizophrenia", "treatment-resistant schizophrenia", "psychosis"]},

    # Urinary & prostate medications
    "Tamsulosin": {"search": ["tamsulosin"], "strength": 0.4, "symptoms": ["prostate", "BPH", "urinary problems", "difficulty urinating", "enlarged prostate"]},
    "Finasteride": {"search": ["finasteride"], "strength": 5, "symptoms": ["prostate", "BPH", "hair loss", "male pattern baldness", "enlarged prostate", "urinary problems"]},

    # Vitamins & supplements
    "Vitamin D": {"search": ["vitamin d"], "strength": 0.01, "symptoms": ["vitamin deficiency", "bone health", "immune system", "calcium absorption", "osteoporosis"]},
    "Calcium Carbonate": {"search": ["calcium carbonate"], "strength": 600, "symptoms": ["calcium supplement", "bone health", "osteoporosis", "heartburn", "antacid"]},
    "Iron Supplement": {"search": ["iron"], "strength": 65, "symptoms": ["anemia", "iron deficiency", "fatigue", "low iron", "blood"]},
    "Folic Acid": {"search": ["folic acid"], "strength": 0.001, "symptoms": ["pregnancy", "vitamin deficiency", "neural tube defects", "anemia", "prenatal"]},
    "Potassium Chloride": {"search": ["potassium chloride"], "strength": 20, "symptoms": ["potassium deficiency", "low potassium", "electrolyte", "muscle cramps"]},
    "Magnesium Oxide": {"search": ["magnesium oxide"], "strength": 400, "symptoms": ["magnesium deficiency", "constipation", "muscle cramps", "migraine", "heartburn"]},
    "Vitamin B12": {"search": ["vitamin b12"], "strength": 0.001, "symptoms": ["vitamin deficiency", "anemia", "nerve health", "energy", "fatigue"]},
    "Vitamin C": {"search": ["vitamin c"], "strength": 500, "symptoms": ["immune system", "vitamin deficiency", "scurvy", "cold prevention", "antioxidant"]},
    "Vitamin E": {"search": ["vitamin e"], "strength": 400, "symptoms": ["antioxidant", "vitamin deficiency", "skin health", "immune system"]},
    "Omega-3 Fish Oil": {"search": ["omega 3"], "strength": 1000, "symptoms": ["heart health", "omega-3", "triglycerides", "brain health", "inflammation", "joint health"]},
    "Coenzyme Q10": {"search": ["coenzyme q10"], "strength": 100, "symptoms": ["heart health", "energy", "antioxidant", "migraine", "statin side effects"]},
    "Melatonin": {"search": ["melatonin"], "strength": 3, "symptoms": ["insomnia", "sleeping aid", "jet lag", "sleep disorder", "trouble sleeping"]},
    "Zinc": {"search": ["zinc"], "strength": 50, "symptoms": ["immune system", "vitamin deficiency", "wound healing", "cold symptoms", "acne"]},
    "Biotin": {"search": ["biotin"], "strength": 0.001, "symptoms": ["hair growth", "nail health", "skin health", "vitamin deficiency"]},
    "Glucosamine": {"search": ["glucosamine"], "strength": 500, "symptoms": ["joint health", "arthritis", "osteoarthritis", "joint pain", "cartilage"]},
    "Turmeric/Curcumin": {"search": ["curcumin"], "strength": 500, "symptoms": ["inflammation", "joint pain", "arthritis", "antioxidant", "pain relief"]},

    # Topical medications
    "Hydrocortisone Cream": {"search": ["hydrocortisone"], "strength": 10, "symptoms": ["itching", "skin irritation", "rash", "eczema", "insect bites", "dermatitis"]},
    "Benzoyl Peroxide": {"search": ["benzoyl peroxide"], "strength": 50, "symptoms": ["acne", "pimples", "skin infection", "bacterial acne", "breakouts"]},
    "Salicylic Acid": {"search": ["salicylic acid"], "strength": 170, "symptoms": ["acne", "warts", "dandruff", "skin exfoliation", "pimples", "blackheads"]},
    "Adapalene": {"search": ["adapalene"], "strength": 0.1, "symptoms": ["acne", "pimples", "skin renewal", "breakouts", "clogged pores"]},
    "Tretinoin": {"search": ["tretinoin"], "strength": 0.025, "symptoms": ["acne", "wrinkles", "skin aging", "skin renewal", "fine lines", "dark spots"]},
    "Clotrimazole": {"search": ["clotrimazole"], "strength": 10, "symptoms": ["fungal infection", "athlete's foot", "ringworm", "yeast infection", "jock itch"]},
    "Miconazole": {"search": ["miconazole"], "strength": 20, "symptoms": ["fungal infection", "yeast infection", "athlete's foot", "ringworm", "jock itch"]},
    "Neomycin/Bacitracin": {"search": ["neomycin bacitracin"], "strength": 0.5, "symptoms": ["wound care", "skin infection", "cuts", "burns", "prevention of infection"]},
    "Lidocaine": {"search": ["lidocaine"], "strength": 50, "symptoms": ["numbing", "pain relief", "itching", "burning", "topical anesthesia", "sunburn"]},
    "Prilocaine/Lidocaine": {"search": ["prilocaine lidocaine"], "strength": 20, "symptoms": ["numbing", "pain relief", "topical anesthesia", "procedure pain"]},
    "Diclofenac Gel": {"search": ["diclofenac"], "strength": 12.5, "symptoms": ["arthritis", "joint pain", "pain relief", "inflammation", "osteoarthritis", "topical pain"]},
    "Ketoconazole": {"search": ["ketoconazole"], "strength": 20, "symptoms": ["fungal infection", "dandruff", "seborrheic dermatitis", "ringworm", "yeast"]},
    "Terbinafine": {"search": ["terbinafine"], "strength": 25, "symptoms": ["fungal infection", "athlete's foot", "ringworm", "nail fungus", "jock itch"]},
    "Acyclovir Cream": {"search": ["acyclovir"], "strength": 40, "symptoms": ["cold sores", "herpes", "viral infection", "lip sore", "topical antiviral"]},
    "Pimecrolimus": {"search": ["pimecrolimus"], "strength": 10, "symptoms": ["eczema", "atopic dermatitis", "skin inflammation", "itching", "rash"]},
    "Tacrolimus": {"search": ["tacrolimus"], "strength": 0.01, "symptoms": ["eczema", "atopic dermatitis", "skin inflammation", "autoimmune", "transplant"]},

    # Eye & ear medications
    "Artificial Tears": {"search": ["artificial tears"], "strength": 10, "symptoms": ["dry eyes", "eye irritation", "eye lubrication", "contact lenses", "eye discomfort"]},
    "Ketotifen Eye Drops": {"search": ["ketotifen"], "strength": 0.025, "symptoms": ["itchy eyes", "eye allergies", "allergic conjunctivitis", "red eyes"]},
    "Ciprofloxacin Ear Drops": {"search": ["ciprofloxacin"], "strength": 0.3, "symptoms": ["ear infection", "swimmer's ear", "bacterial ear infection", "otitis externa"]},
    "Ofloxacin Ear Drops": {"search": ["ofloxacin"], "strength": 0.3, "symptoms": ["ear infection", "bacterial ear infection", "otitis media", "ear tube infection"]},

    # Additional commonly prescribed medications
    "Isosorbide Mononitrate": {"search": ["isosorbide mononitrate"], "strength": 30, "symptoms": ["chest pain", "angina", "heart health", "coronary artery disease"]},
    "Nitroglycerin": {"search": ["nitroglycerin"], "strength": 0.4, "symptoms": ["chest pain", "angina", "heart attack", "heart health", "emergency heart"]},
    "Amiodarone": {"search": ["amiodarone"], "strength": 200, "symptoms": ["irregular heartbeat", "arrhythmia", "atrial fibrillation", "ventricular tachycardia"]},
    "Sulfasalazine": {"search": ["sulfasalazine"], "strength": 500, "symptoms": ["rheumatoid arthritis", "ulcerative colitis", "IBD", "inflammatory bowel disease", "joint pain"]},
    "Niacin": {"search": ["niacin"], "strength": 500, "symptoms": ["cholesterol", "vitamin deficiency", "high cholesterol", "triglycerides", "B3"]},
    "Isotretinoin": {"search": ["isotretinoin"], "strength": 10, "symptoms": ["severe acne", "cystic acne", "acne scarring", "hormonal acne"]},
    "Azelaic Acid": {"search": ["azelaic acid"], "strength": 10, "symptoms": ["acne", "rosacea", "skin discoloration", "dark spots", "skin irritation"]},
    "Tranexamic Acid": {"search": ["tranexamic acid"], "strength": 250, "symptoms": ["bleeding", "heavy periods", "nosebleed", "clotting", "excessive bleeding"]},
    "Hydroquinone": {"search": ["hydroquinone"], "strength": 20, "symptoms": ["skin lightening", "dark spots", "melasma", "hyperpigmentation", "age spots"]},

    # Hormones & endocrine medications
    "Estradiol": {"search": ["estradiol"], "strength": 1, "symptoms": ["menopause", "hormone replacement", "low estrogen", "hot flashes", "vaginal dryness"]},
    "Progesterone": {"search": ["progesterone"], "strength": 100, "symptoms": ["menopause", "hormone replacement", "irregular periods", "infertility", "pregnancy support"]},
    "Testosterone": {"search": ["testosterone"], "strength": 300, "symptoms": ["low testosterone", "low libido", "hormone replacement", "muscle loss", "fatigue"]},
    "Spironolactone (Anti-androgen)": {"search": ["spironolactone"], "strength": 25, "symptoms": ["acne", "hirsutism", "high blood pressure", "hormonal acne", "excess hair"]},
    "Cyproterone": {"search": ["cyproterone"], "strength": 50, "symptoms": ["hormonal disorder", "prostate cancer", "hirsutism", "sexual disorder"]},
    "Desogestrel": {"search": ["desogestrel"], "strength": 0.15, "symptoms": ["birth control", "contraception", "pregnancy prevention", "period regulation"]},
    "Norethindrone": {"search": ["norethindrone"], "strength": 5, "symptoms": ["birth control", "irregular periods", "endometriosis", "contraception"]},
    "Ethinyl Estradiol/Norethindrone": {"search": ["ethinyl estradiol norethindrone"], "strength": 0.02, "symptoms": ["birth control", "contraception", "pregnancy prevention", "period regulation", "acne"]},
    "Levonorgestrel": {"search": ["levonorgestrel"], "strength": 0.15, "symptoms": ["emergency contraception", "morning after pill", "pregnancy prevention"]},
    "Clomiphene": {"search": ["clomiphene"], "strength": 50, "symptoms": ["infertility", "ovulation", "PCOS", "fertility treatment"]},
    "Letrozole": {"search": ["letrozole"], "strength": 2.5, "symptoms": ["breast cancer", "infertility", "ovulation", "hormone-sensitive cancer"]},
    "Metformin (PCOS)": {"search": ["metformin"], "strength": 500, "symptoms": ["PCOS", "polycystic ovary syndrome", "insulin resistance", "irregular periods", "fertility"]},
    "Desmopressin": {"search": ["desmopressin"], "strength": 0.1, "symptoms": ["diabetes insipidus", "bedwetting", "excessive urination", "bleeding disorder"]},
    "Hydrocortisone": {"search": ["hydrocortisone"], "strength": 10, "symptoms": ["adrenal insufficiency", "inflammation", "allergies", "skin condition", "hormone replacement"]},
    "Fludrocortisone": {"search": ["fludrocortisone"], "strength": 0.1, "symptoms": ["adrenal insufficiency", "low blood pressure", "Addison's disease", "salt wasting"]},
    "Calcitriol": {"search": ["calcitriol"], "strength": 0.005, "symptoms": ["vitamin D", "kidney disease", "low calcium", "osteoporosis", "parathyroid"]},
    "Alendronate": {"search": ["alendronate"], "strength": 70, "symptoms": ["osteoporosis", "bone health", "bone density", "fracture prevention"]},
    "Risedronate": {"search": ["risedronate"], "strength": 35, "symptoms": ["osteoporosis", "bone health", "Paget's disease", "fracture prevention"]},
    "Ibandronate": {"search": ["ibandronate"], "strength": 150, "symptoms": ["osteoporosis", "bone density", "fracture prevention", "postmenopausal"]},
    "Zoledronic Acid": {"search": ["zoledronic acid"], "strength": 4, "symptoms": ["osteoporosis", "bone cancer", "high calcium", "Paget's disease", "fracture prevention"]},
    "Denosumab": {"search": ["denosumab"], "strength": 60, "symptoms": ["osteoporosis", "bone cancer", "bone metastasis", "fracture prevention"]},
    "Teriparatide": {"search": ["teriparatide"], "strength": 20, "symptoms": ["osteoporosis", "bone density", "fracture risk", "severe osteoporosis"]},

    # Antiviral medications
    "Oseltamivir": {"search": ["oseltamivir"], "strength": 75, "symptoms": ["flu", "influenza", "viral infection", "flu prevention", "fever"]},
    "Remdesivir": {"search": ["remdesivir"], "strength": 100, "symptoms": ["viral infection", "COVID-19", "respiratory virus", "Ebola"]},
    "Sofosbuvir": {"search": ["sofosbuvir"], "strength": 400, "symptoms": ["hepatitis C", "liver disease", "viral hepatitis", "HCV"]},
    "Ledipasvir/Sofosbuvir": {"search": ["ledipasvir sofosbuvir"], "strength": 90, "symptoms": ["hepatitis C", "liver disease", "viral hepatitis", "HCV"]},
    "Velpatasvir/Sofosbuvir": {"search": ["velpatasvir sofosbuvir"], "strength": 400, "symptoms": ["hepatitis C", "liver disease", "viral hepatitis", "HCV"]},
    "Ganciclovir": {"search": ["ganciclovir"], "strength": 500, "symptoms": ["CMV", "cytomegalovirus", "viral infection", "eye infection", "immunocompromised"]},
    "Valganciclovir": {"search": ["valganciclovir"], "strength": 450, "symptoms": ["CMV", "cytomegalovirus", "viral infection", "retinitis"]},
    "Famciclovir": {"search": ["famciclovir"], "strength": 250, "symptoms": ["shingles", "herpes", "viral infection", "cold sores", "genital herpes"]},
    "Ribavirin": {"search": ["ribavirin"], "strength": 200, "symptoms": ["hepatitis C", "viral infection", "HCV", "respiratory syncytial virus"]},
    "Interferon": {"search": ["interferon"], "strength": 100, "symptoms": ["hepatitis", "viral infection", "cancer", "multiple sclerosis", "immune system"]},
    "Tenofovir": {"search": ["tenofovir"], "strength": 300, "symptoms": ["HIV", "AIDS", "hepatitis B", "viral infection", "PrEP"]},
    "Emtricitabine/Tenofovir": {"search": ["emtricitabine tenofovir"], "strength": 200, "symptoms": ["HIV", "AIDS", "PrEP", "HIV prevention", "viral infection"]},
    "Dolutegravir": {"search": ["dolutegravir"], "strength": 50, "symptoms": ["HIV", "AIDS", "viral infection", "HIV treatment"]},
    "Raltegravir": {"search": ["raltegravir"], "strength": 400, "symptoms": ["HIV", "AIDS", "viral infection", "HIV treatment"]},
    "Efavirenz": {"search": ["efavirenz"], "strength": 200, "symptoms": ["HIV", "AIDS", "viral infection", "HIV treatment"]},
    "Lamivudine": {"search": ["lamivudine"], "strength": 300, "symptoms": ["HIV", "AIDS", "hepatitis B", "viral infection"]},
    "Zidovudine": {"search": ["zidovudine"], "strength": 300, "symptoms": ["HIV", "AIDS", "viral infection", "HIV treatment", "pregnancy HIV"]},
    "Abacavir": {"search": ["abacavir"], "strength": 300, "symptoms": ["HIV", "AIDS", "viral infection", "HIV treatment"]},
    "Atazanavir": {"search": ["atazanavir"], "strength": 300, "symptoms": ["HIV", "AIDS", "viral infection", "HIV treatment"]},
    "Darunavir": {"search": ["darunavir"], "strength": 600, "symptoms": ["HIV", "AIDS", "viral infection", "HIV treatment"]},
    "Boceprevir": {"search": ["boceprevir"], "strength": 800, "symptoms": ["hepatitis C", "liver disease", "viral hepatitis"]},
    "Telaprevir": {"search": ["telaprevir"], "strength": 750, "symptoms": ["hepatitis C", "liver disease", "viral hepatitis"]},

    # Cancer & chemotherapy medications
    "Methotrexate": {"search": ["methotrexate"], "strength": 2.5, "symptoms": ["cancer", "rheumatoid arthritis", "psoriasis", "chemotherapy", "autoimmune"]},
    "Cyclophosphamide": {"search": ["cyclophosphamide"], "strength": 50, "symptoms": ["cancer", "chemotherapy", "lymphoma", "leukemia", "autoimmune"]},
    "Doxorubicin": {"search": ["doxorubicin"], "strength": 2, "symptoms": ["cancer", "chemotherapy", "lymphoma", "breast cancer", "bladder cancer"]},
    "Paclitaxel": {"search": ["paclitaxel"], "strength": 6, "symptoms": ["cancer", "chemotherapy", "breast cancer", "ovarian cancer", "lung cancer"]},
    "Carboplatin": {"search": ["carboplatin"], "strength": 15, "symptoms": ["cancer", "chemotherapy", "ovarian cancer", "lung cancer", "cervical cancer"]},
    "Cisplatin": {"search": ["cisplatin"], "strength": 1, "symptoms": ["cancer", "chemotherapy", "testicular cancer", "ovarian cancer", "bladder cancer"]},
    "5-Fluorouracil": {"search": ["fluorouracil"], "strength": 500, "symptoms": ["cancer", "chemotherapy", "colon cancer", "breast cancer", "skin cancer"]},
    "Capecitabine": {"search": ["capecitabine"], "strength": 500, "symptoms": ["cancer", "chemotherapy", "breast cancer", "colon cancer", "gastric cancer"]},
    "Tamoxifen": {"search": ["tamoxifen"], "strength": 20, "symptoms": ["breast cancer", "hormone receptor positive", "cancer prevention", "hormone therapy"]},
    "Anastrozole": {"search": ["anastrozole"], "strength": 1, "symptoms": ["breast cancer", "hormone therapy", "postmenopausal", "cancer treatment"]},
    "Letrozole (Cancer)": {"search": ["letrozole"], "strength": 2.5, "symptoms": ["breast cancer", "hormone therapy", "cancer treatment", "postmenopausal"]},
    "Exemestane": {"search": ["exemestane"], "strength": 25, "symptoms": ["breast cancer", "hormone therapy", "cancer treatment", "postmenopausal"]},
    "Imatinib": {"search": ["imatinib"], "strength": 100, "symptoms": ["cancer", "leukemia", "CML", "GIST", "targeted therapy"]},
    "Sunitinib": {"search": ["sunitinib"], "strength": 50, "symptoms": ["cancer", "kidney cancer", "GIST", "targeted therapy"]},
    "Sorafenib": {"search": ["sorafenib"], "strength": 200, "symptoms": ["cancer", "liver cancer", "kidney cancer", "thyroid cancer", "targeted therapy"]},
    "Erlotinib": {"search": ["erlotinib"], "strength": 150, "symptoms": ["cancer", "lung cancer", "pancreatic cancer", "targeted therapy"]},
    "Gefitinib": {"search": ["gefitinib"], "strength": 250, "symptoms": ["cancer", "lung cancer", "targeted therapy", "NSCLC"]},
    "Crizotinib": {"search": ["crizotinib"], "strength": 250, "symptoms": ["cancer", "lung cancer", "ALK-positive", "targeted therapy"]},
    "Vemurafenib": {"search": ["vemurafenib"], "strength": 240, "symptoms": ["cancer", "melanoma", "skin cancer", "targeted therapy", "BRAF mutation"]},
    "Dabrafenib": {"search": ["dabrafenib"], "strength": 50, "symptoms": ["cancer", "melanoma", "targeted therapy", "BRAF mutation"]},
    "Trametinib": {"search": ["trametinib"], "strength": 2, "symptoms": ["cancer", "melanoma", "targeted therapy", "MEK inhibitor"]},
    "Olaparib": {"search": ["olaparib"], "strength": 100, "symptoms": ["cancer", "ovarian cancer", "breast cancer", "BRCA mutation", "targeted therapy"]},
    "Bosutinib": {"search": ["bosutinib"], "strength": 100, "symptoms": ["cancer", "leukemia", "CML", "targeted therapy"]},
    "Dasatinib": {"search": ["dasatinib"], "strength": 20, "symptoms": ["cancer", "leukemia", "CML", "targeted therapy"]},
    "Nilotinib": {"search": ["nilotinib"], "strength": 150, "symptoms": ["cancer", "leukemia", "CML", "targeted therapy"]},
    "Ponatinib": {"search": ["ponatinib"], "strength": 45, "symptoms": ["cancer", "leukemia", "CML", "targeted therapy"]},
    "Ruxolitinib": {"search": ["ruxolitinib"], "strength": 15, "symptoms": ["cancer", "myelofibrosis", "polycythemia vera", "graft vs host"]},
    "Tofacitinib": {"search": ["tofacitinib"], "strength": 5, "symptoms": ["rheumatoid arthritis", "psoriatic arthritis", "ulcerative colitis", "autoimmune"]},
    "Baricitinib": {"search": ["baricitinib"], "strength": 2, "symptoms": ["rheumatoid arthritis", "alopecia areata", "autoimmune", "joint pain"]},
    "Upadacitinib": {"search": ["upadacitinib"], "strength": 15, "symptoms": ["rheumatoid arthritis", "Crohn's disease", "ulcerative colitis", "autoimmune"]},
    "Filgotinib": {"search": ["filgotinib"], "strength": 200, "symptoms": ["rheumatoid arthritis", "autoimmune", "joint pain"]},

    # Gastrointestinal medications
    "Loperamide (Imodium)": {"search": ["loperamide"], "strength": 2, "symptoms": ["diarrhea", "upset stomach", "loose stools", "IBS diarrhea"]},
    "Diphenoxylate/Atropine": {"search": ["diphenoxylate atropine"], "strength": 2.5, "symptoms": ["diarrhea", "loose stools", "bowel movement"]},
    "Bismuth Subsalicylate": {"search": ["bismuth subsalicylate"], "strength": 262, "symptoms": ["upset stomach", "diarrhea", "nausea", "heartburn", "indigestion"]},
    "Lactulose": {"search": ["lactulose"], "strength": 10, "symptoms": ["constipation", "hepatic encephalopathy", "bowel movement", "liver disease"]},
    "Ursodiol": {"search": ["ursodiol"], "strength": 300, "symptoms": ["gallstones", "liver disease", "bile duct", "cholesterol gallstones"]},
    "Pancrelipase": {"search": ["pancrelipase"], "strength": 14000, "symptoms": ["pancreatic insufficiency", "cystic fibrosis", "digestion", "malabsorption"]},
    "Orlistat": {"search": ["orlistat"], "strength": 120, "symptoms": ["weight loss", "obesity", "fat absorption", "diet aid"]},
    "Linaclotide": {"search": ["linaclotide"], "strength": 0.000143, "symptoms": ["IBS", "constipation", "IBS-C", "abdominal pain", "irritable bowel"]},
    "Lubiprostone": {"search": ["lubiprostone"], "strength": 0.00024, "symptoms": ["constipation", "IBS-C", "chronic constipation", "irritable bowel"]},
    "Plecanatide": {"search": ["plecanatide"], "strength": 3, "symptoms": ["constipation", "IBS-C", "chronic constipation", "irritable bowel"]},
    "Tegaserod": {"search": ["tegaserod"], "strength": 6, "symptoms": ["IBS", "IBS-C", "irritable bowel", "constipation", "abdominal pain"]},
    "Prucalopride": {"search": ["prucalopride"], "strength": 2, "symptoms": ["constipation", "chronic constipation", "bowel movement"]},
    "Rifaximin": {"search": ["rifaximin"], "strength": 550, "symptoms": ["IBS", "traveler's diarrhea", "hepatic encephalopathy", "bacterial overgrowth"]},
    "Eluxadoline": {"search": ["eluxadoline"], "strength": 100, "symptoms": ["IBS", "IBS-D", "diarrhea", "irritable bowel", "abdominal pain"]},
    "Alosetron": {"search": ["alosetron"], "strength": 1, "symptoms": ["IBS", "IBS-D", "diarrhea", "irritable bowel", "women IBS"]},
    "Misoprostol": {"search": ["misoprostol"], "strength": 0.2, "symptoms": ["stomach ulcer", "NSAID ulcer prevention", "labor induction", "abortion"]},
    "Sucralfate": {"search": ["sucralfate"], "strength": 1000, "symptoms": ["stomach ulcer", "duodenal ulcer", "acid reflux", "GI ulcer"]},
    "Ranitidine": {"search": ["ranitidine"], "strength": 150, "symptoms": ["heartburn", "acid reflux", "stomach ulcer", "indigestion"]},
    "Nizatidine": {"search": ["nizatidine"], "strength": 150, "symptoms": ["heartburn", "stomach ulcer", "acid reflux", "GERD"]},
    "Proton Pump Inhibitor (Generic)": {"search": ["omeprazole"], "strength": 20, "symptoms": ["acid reflux", "heartburn", "GERD", "stomach ulcer", "indigestion"]},

    # Immunosuppressants
    "Azathioprine": {"search": ["azathioprine"], "strength": 50, "symptoms": ["autoimmune", "rheumatoid arthritis", "transplant", "IBD", "lupus"]},
    "Mycophenolate": {"search": ["mycophenolate"], "strength": 360, "symptoms": ["transplant", "autoimmune", "organ rejection", "lupus"]},
    "Cyclosporine": {"search": ["cyclosporine"], "strength": 25, "symptoms": ["transplant", "autoimmune", "rheumatoid arthritis", "psoriasis", "organ rejection"]},
    "Tacrolimus (Oral)": {"search": ["tacrolimus"], "strength": 1, "symptoms": ["transplant", "organ rejection", "autoimmune", "immunosuppression"]},
    "Sirolimus": {"search": ["sirolimus"], "strength": 1, "symptoms": ["transplant", "organ rejection", "cancer", "immunosuppression"]},
    "Everolimus": {"search": ["everolimus"], "strength": 0.5, "symptoms": ["transplant", "cancer", "organ rejection", "tuberous sclerosis"]},
    "Methotrexate (Rheumatoid)": {"search": ["methotrexate"], "strength": 2.5, "symptoms": ["rheumatoid arthritis", "psoriasis", "autoimmune", "joint pain", "inflammation"]},
    "Leflunomide": {"search": ["leflunomide"], "strength": 10, "symptoms": ["rheumatoid arthritis", "psoriatic arthritis", "autoimmune", "joint pain"]},
    "Hydroxychloroquine": {"search": ["hydroxychloroquine"], "strength": 200, "symptoms": ["lupus", "rheumatoid arthritis", "autoimmune", "malaria prevention", "joint pain"]},
    "Sulfasalazine (Rheumatoid)": {"search": ["sulfasalazine"], "strength": 500, "symptoms": ["rheumatoid arthritis", "ulcerative colitis", "IBD", "joint pain", "autoimmune"]},
    "Adalimumab": {"search": ["adalimumab"], "strength": 40, "symptoms": ["rheumatoid arthritis", "Crohn's disease", "psoriasis", "autoimmune", "IBD", "joint pain"]},
    "Etanercept": {"search": ["etanercept"], "strength": 50, "symptoms": ["rheumatoid arthritis", "psoriasis", "ankylosing spondylitis", "autoimmune", "joint pain"]},
    "Infliximab": {"search": ["infliximab"], "strength": 100, "symptoms": ["rheumatoid arthritis", "Crohn's disease", "ulcerative colitis", "autoimmune", "IBD"]},
    "Certolizumab": {"search": ["certolizumab"], "strength": 200, "symptoms": ["rheumatoid arthritis", "Crohn's disease", "psoriasis", "autoimmune"]},
    "Golimumab": {"search": ["golimumab"], "strength": 50, "symptoms": ["rheumatoid arthritis", "ulcerative colitis", "psoriasis", "autoimmune", "joint pain"]},
    "Ustekinumab": {"search": ["ustekinumab"], "strength": 45, "symptoms": ["psoriasis", "Crohn's disease", "ulcerative colitis", "autoimmune"]},
    "Secukinumab": {"search": ["secukinumab"], "strength": 150, "symptoms": ["psoriasis", "ankylosing spondylitis", "psoriatic arthritis", "autoimmune"]},
    "Ixekizumab": {"search": ["ixekizumab"], "strength": 75, "symptoms": ["psoriasis", "psoriatic arthritis", "ankylosing spondylitis", "autoimmune"]},
    "Tocilizumab": {"search": ["tocilizumab"], "strength": 162, "symptoms": ["rheumatoid arthritis", "giant cell arteritis", "autoimmune", "joint pain"]},
    "Abatacept": {"search": ["abatacept"], "strength": 125, "symptoms": ["rheumatoid arthritis", "psoriatic arthritis", "autoimmune", "joint pain"]},
    "Anakinra": {"search": ["anakinra"], "strength": 100, "symptoms": ["rheumatoid arthritis", "autoimmune", "fever syndrome", "joint pain"]},
    "Canakinumab": {"search": ["canakinumab"], "strength": 150, "symptoms": ["autoimmune", "fever syndrome", "inflammation", "rheumatologic"]},
    "Sarilumab": {"search": ["sarilumab"], "strength": 150, "symptoms": ["rheumatoid arthritis", "autoimmune", "joint pain", "inflammation"]},
    "Baricitinib (Rheumatoid)": {"search": ["baricitinib"], "strength": 2, "symptoms": ["rheumatoid arthritis", "autoimmune", "joint pain", "alopecia"]},

    # Blood & clotting medications
    "Heparin": {"search": ["heparin"], "strength": 5000, "symptoms": ["blood thinner", "clot prevention", "DVT", "blood clot", "anticoagulant"]},
    "Enoxaparin": {"search": ["enoxaparin"], "strength": 40, "symptoms": ["blood thinner", "clot prevention", "DVT", "blood clot", "anticoagulant"]},
    "Dalteparin": {"search": ["dalteparin"], "strength": 25000, "symptoms": ["blood thinner", "clot prevention", "DVT", "blood clot"]},
    "Fondaparinux": {"search": ["fondaparinux"], "strength": 2.5, "symptoms": ["blood thinner", "clot prevention", "DVT", "blood clot", "anticoagulant"]},
    "Enoxaparin (Prevention)": {"search": ["enoxaparin"], "strength": 40, "symptoms": ["blood thinner", "clot prevention", "DVT", "blood clot"]},
    "Tissue Plasminogen Activator": {"search": ["tissue plasminogen activator"], "strength": 5, "symptoms": ["blood clot", "stroke", "heart attack", "clot dissolution", "DVT"]},
    "Streptokinase": {"search": ["streptokinase"], "strength": 250000, "symptoms": ["blood clot", "heart attack", "clot dissolution", "pulmonary embolism"]},
    "Urokinase": {"search": ["urokinase"], "strength": 5000, "symptoms": ["blood clot", "clot dissolution", "pulmonary embolism"]},
    "Tranexamic Acid (Clotting)": {"search": ["tranexamic acid"], "strength": 500, "symptoms": ["bleeding", "heavy periods", "nosebleed", "clotting", "excessive bleeding"]},
    "Aminocaproic Acid": {"search": ["aminocaproic acid"], "strength": 1000, "symptoms": ["bleeding", "clotting", "excessive bleeding", "hemorrhage"]},
    "Desmopressin (Clotting)": {"search": ["desmopressin"], "strength": 0.1, "symptoms": ["bleeding disorder", "hemophilia", "von Willebrand", "clotting"]},
    "Vitamin K": {"search": ["vitamin k"], "strength": 5, "symptoms": ["vitamin deficiency", "bleeding", "clotting", "warfarin reversal", "newborn"]},
    "Iron Sucrose": {"search": ["iron sucrose"], "strength": 20, "symptoms": ["anemia", "iron deficiency", "kidney disease", "low iron", "fatigue"]},
    "Ferrous Sulfate": {"search": ["ferrous sulfate"], "strength": 325, "symptoms": ["anemia", "iron deficiency", "low iron", "fatigue", "pregnancy"]},
    "Ferrous Gluconate": {"search": ["ferrous gluconate"], "strength": 325, "symptoms": ["anemia", "iron deficiency", "low iron", "gentle iron"]},
    "Ferrous Fumarate": {"search": ["ferrous fumarate"], "strength": 325, "symptoms": ["anemia", "iron deficiency", "low iron", "fatigue"]},
    "Epoetin Alfa": {"search": ["epoetin"], "strength": 10000, "symptoms": ["anemia", "kidney disease", "chemotherapy anemia", "low red blood cells"]},
    "Darbepoetin": {"search": ["darbepoetin"], "strength": 0.004, "symptoms": ["anemia", "kidney disease", "chemotherapy anemia", "low red blood cells"]},
    "Pegfilgrastim": {"search": ["pegfilgrastim"], "strength": 6, "symptoms": ["low white blood cells", "chemotherapy", "neutropenia", "immune system"]},
    "Filgrastim": {"search": ["filgrastim"], "strength": 480, "symptoms": ["low white blood cells", "neutropenia", "chemotherapy", "bone marrow"]},
    "Oprelvekin": {"search": ["oprelvekin"], "strength": 30000, "symptoms": ["low platelets", "chemotherapy", "thrombocytopenia"]},

    # Ophthalmic medications
    "Latanoprost": {"search": ["latanoprost"], "strength": 0.005, "symptoms": ["glaucoma", "eye pressure", "high eye pressure", "open-angle glaucoma", "ocular hypertension"]},
    "Bimatoprost": {"search": ["bimatoprost"], "strength": 0.003, "symptoms": ["glaucoma", "eye pressure", "eyelash growth", "ocular hypertension"]},
    "Travoprost": {"search": ["travoprost"], "strength": 0.004, "symptoms": ["glaucoma", "eye pressure", "open-angle glaucoma", "ocular hypertension"]},
    "Timolol Eye Drops": {"search": ["timolol"], "strength": 0.005, "symptoms": ["glaucoma", "eye pressure", "high eye pressure", "ocular hypertension"]},
    "Brimonidine": {"search": ["brimonidine"], "strength": 0.002, "symptoms": ["glaucoma", "eye pressure", "red eyes", "ocular hypertension"]},
    "Dorzolamide": {"search": ["dorzolamide"], "strength": 0.02, "symptoms": ["glaucoma", "eye pressure", "open-angle glaucoma", "ocular hypertension"]},
    "Acetazolamide": {"search": ["acetazolamide"], "strength": 250, "symptoms": ["glaucoma", "eye pressure", "altitude sickness", "seizures", "edema"]},
    "Prednisolone Eye Drops": {"search": ["prednisolone"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery", "eye infection", "eye redness"]},
    "Dexamethasone Eye Drops": {"search": ["dexamethasone"], "strength": 0.1, "symptoms": ["eye inflammation", "eye allergy", "eye surgery", "eye redness"]},
    "Cyclopentolate": {"search": ["cyclopentolate"], "strength": 0.01, "symptoms": ["eye exam", "pupil dilation", "eye procedure", "eye spasms"]},
    "Tropicamide": {"search": ["tropicamide"], "strength": 0.01, "symptoms": ["eye exam", "pupil dilation", "eye procedure"]},
    "Phenylephrine Eye Drops": {"search": ["phenylephrine"], "strength": 0.025, "symptoms": ["red eyes", "eye exam", "pupil dilation", "eye irritation"]},
    "Naphazoline Eye Drops": {"search": ["naphazoline"], "strength": 0.005, "symptoms": ["red eyes", "eye irritation", "eye redness", "eye itching"]},
    "Ketorolac Eye Drops": {"search": ["ketorolac"], "strength": 0.005, "symptoms": ["eye pain", "eye inflammation", "eye allergy", "itchy eyes", "eye surgery"]},
    "Moxifloxacin Eye Drops": {"search": ["moxifloxacin"], "strength": 0.005, "symptoms": ["eye infection", "bacterial eye infection", "pink eye", "corneal ulcer"]},
    "Ofloxacin Eye Drops": {"search": ["ofloxacin"], "strength": 0.003, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Ciprofloxacin Eye Drops": {"search": ["ciprofloxacin"], "strength": 0.003, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Fluorometholone": {"search": ["fluorometholone"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery", "eye redness"]},
    "Loteprednol": {"search": ["loteprednol"], "strength": 0.002, "symptoms": ["eye inflammation", "eye allergy", "eye surgery", "eye redness"]},
    "Rifampin Eye Drops": {"search": ["rifampin"], "strength": 0.005, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Vigamox Eye Drops": {"search": ["moxifloxacin"], "strength": 0.005, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Ciloxan Eye Drops": {"search": ["ciprofloxacin"], "strength": 0.003, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Zymaxid Eye Drops": {"search": ["gatifloxacin"], "strength": 0.003, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Aflac Eye Drops": {"search": ["aflac"], "strength": 0.005, "symptoms": ["eye infection", "bacterial eye infection"]},
    "Moxeza Eye Drops": {"search": ["moxifloxacin"], "strength": 0.005, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Istalol Eye Drops": {"search": ["isoflupredone"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery"]},
    "Pred Forte Eye Drops": {"search": ["prednisolone"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery", "eye redness"]},
    "Maxidex Eye Drops": {"search": ["dexamethasone"], "strength": 0.1, "symptoms": ["eye inflammation", "eye allergy", "eye surgery"]},
    "Ak-Pred Eye Drops": {"search": ["prednisolone"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery"]},
    "Ocu-Pred Eye Drops": {"search": ["prednisolone"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery"]},
    "Prednisolone Acetate Eye Drops": {"search": ["prednisolone acetate"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery", "eye redness"]},
    "Durezol Eye Drops": {"search": ["difluprednate"], "strength": 0.005, "symptoms": ["eye inflammation", "eye surgery", "eye allergy", "eye redness"]},
    "Yutiq Eye Drops": {"search": ["dexamethasone"], "strength": 0.1, "symptoms": ["eye inflammation", "diabetic macular edema", "eye surgery"]},
    "Iluvien Eye Drops": {"search": ["dexamethasone"], "strength": 0.7, "symptoms": ["diabetic macular edema", "eye swelling", "vision loss"]},
    "Ozurdex": {"search": ["dexamethasone implant"], "strength": 0.7, "symptoms": ["eye inflammation", "diabetic macular edema", "retinal vein occlusion", "vision loss"]},

    # Additional commonly prescribed medications
    "Chlorpromazine": {"search": ["chlorpromazine"], "strength": 25, "symptoms": ["schizophrenia", "psychosis", "nausea", "tourette syndrome", "mania"]},
    "Perphenazine": {"search": ["perphenazine"], "strength": 4, "symptoms": ["schizophrenia", "psychosis", "nausea", "anxiety"]},
    "Trifluoperazine": {"search": ["trifluoperazine"], "strength": 5, "symptoms": ["schizophrenia", "psychosis", "anxiety", "depression"]},
    "Fluphenazine": {"search": ["fluphenazine"], "strength": 2.5, "symptoms": ["schizophrenia", "psychosis", "mania", "delusions"]},
    "Haloperidol Decanoate": {"search": ["haloperidol decanoate"], "strength": 50, "symptoms": ["schizophrenia", "psychosis", "tourette syndrome", "mania"]},
    "Fluphenazine Decanoate": {"search": ["fluphenazine decanoate"], "strength": 25, "symptoms": ["schizophrenia", "psychosis", "mania", "delusions"]},

    # Anti-TB medications
    "Rifampin": {"search": ["rifampin"], "strength": 150, "symptoms": ["tuberculosis", "TB", "bacterial infection", "respiratory infection"]},
    "Isoniazid": {"search": ["isoniazid"], "strength": 100, "symptoms": ["tuberculosis", "TB", "bacterial infection", "latent TB"]},
    "Pyrazinamide": {"search": ["pyrazinamide"], "strength": 500, "symptoms": ["tuberculosis", "TB", "bacterial infection"]},
    "Ethambutol": {"search": ["ethambutol"], "strength": 400, "symptoms": ["tuberculosis", "TB", "bacterial infection"]},
    "Rifampin/Isoniazid": {"search": ["rifampin isoniazid"], "strength": 150, "symptoms": ["tuberculosis", "TB", "bacterial infection", "latent TB"]},

    # Additional antibiotics
    "Vancomycin": {"search": ["vancomycin"], "strength": 500, "symptoms": ["bacterial infection", "MRSA", "skin infection", "blood infection", "C. diff"]},
    "Linezolid": {"search": ["linezolid"], "strength": 600, "symptoms": ["bacterial infection", "MRSA", "pneumonia", "skin infection", "resistant bacteria"]},
    "Daptomycin": {"search": ["daptomycin"], "strength": 500, "symptoms": ["bacterial infection", "MRSA", "blood infection", "skin infection"]},
    "Tigecycline": {"search": ["tigecycline"], "strength": 50, "symptoms": ["bacterial infection", "resistant bacteria", "skin infection", "abdominal infection"]},
    "Fosfomycin": {"search": ["fosfomycin"], "strength": 3000, "symptoms": ["UTI", "urinary tract infection", "bacterial infection", "bladder infection"]},
    "Ceftriaxone": {"search": ["ceftriaxone"], "strength": 1000, "symptoms": ["bacterial infection", "pneumonia", "meningitis", "gonorrhea", "sepsis"]},
    "Cefotaxime": {"search": ["cefotaxime"], "strength": 500, "symptoms": ["bacterial infection", "pneumonia", "meningitis", "sepsis"]},
    "Ceftazidime": {"search": ["ceftazidime"], "strength": 500, "symptoms": ["bacterial infection", "Pseudomonas", "pneumonia", "sepsis"]},
    "Cefepime": {"search": ["cefepime"], "strength": 500, "symptoms": ["bacterial infection", "pneumonia", "sepsis", "UTI"]},
    "Meropenem": {"search": ["meropenem"], "strength": 500, "symptoms": ["bacterial infection", "sepsis", "pneumonia", "resistant bacteria", "meningitis"]},
    "Imipenem/Cilastatin": {"search": ["imipenem cilastatin"], "strength": 500, "symptoms": ["bacterial infection", "sepsis", "pneumonia", "resistant bacteria"]},
    "Ertapenem": {"search": ["ertapenem"], "strength": 500, "symptoms": ["bacterial infection", "UTI", "skin infection", "abdominal infection"]},
    "Piperacillin/Tazobactam": {"search": ["piperacillin tazobactam"], "strength": 4000, "symptoms": ["bacterial infection", "pneumonia", "sepsis", "abdominal infection"]},
    "Ampicillin/Sulbactam": {"search": ["ampicillin sulbactam"], "strength": 3000, "symptoms": ["bacterial infection", "skin infection", "respiratory infection", "abdominal infection"]},
    "Dicloxacillin": {"search": ["dicloxacillin"], "strength": 250, "symptoms": ["bacterial infection", "skin infection", "staph infection"]},
    "Nafcillin": {"search": ["nafcillin"], "strength": 500, "symptoms": ["bacterial infection", "staph infection", "skin infection", "endocarditis"]},
    "Oxacillin": {"search": ["oxacillin"], "strength": 500, "symptoms": ["bacterial infection", "staph infection", "skin infection"]},
    "Cefazolin": {"search": ["cefazolin"], "strength": 500, "symptoms": ["bacterial infection", "surgery prevention", "skin infection", "UTI"]},
    "Cefuroxime": {"search": ["cefuroxime"], "strength": 250, "symptoms": ["bacterial infection", "respiratory infection", "sinus infection", "UTI"]},
    "Cefpodoxime": {"search": ["cefpodoxime"], "strength": 100, "symptoms": ["bacterial infection", "respiratory infection", "ear infection", "UTI"]},
    "Cefdinir": {"search": ["cefdinir"], "strength": 100, "symptoms": ["bacterial infection", "sinus infection", "ear infection", "throat infection"]},
    "Cefixime": {"search": ["cefixime"], "strength": 100, "symptoms": ["bacterial infection", "UTI", "ear infection", "throat infection"]},
    "Ceftibuten": {"search": ["ceftibuten"], "strength": 100, "symptoms": ["bacterial infection", "ear infection", "respiratory infection"]},
    "Cefprozil": {"search": ["cefprozil"], "strength": 250, "symptoms": ["bacterial infection", "skin infection", "respiratory infection", "ear infection"]},
    "Cefaclor": {"search": ["cefaclor"], "strength": 250, "symptoms": ["bacterial infection", "ear infection", "respiratory infection", "throat infection"]},
    "Cefadroxil": {"search": ["cefadroxil"], "strength": 500, "symptoms": ["bacterial infection", "skin infection", "UTI", "throat infection"]},
    "Cefoxitin": {"search": ["cefoxitin"], "strength": 500, "symptoms": ["bacterial infection", "surgery prevention", "skin infection", "abdominal infection"]},
    "Cefotetan": {"search": ["cefotetan"], "strength": 500, "symptoms": ["bacterial infection", "surgery prevention", "abdominal infection"]},

    # Additional ophthalmic
    "Gatifloxacin Eye Drops": {"search": ["gatifloxacin"], "strength": 0.003, "symptoms": ["eye infection", "bacterial eye infection", "pink eye"]},
    "Difluprednate Eye Drops": {"search": ["difluprednate"], "strength": 0.005, "symptoms": ["eye inflammation", "eye surgery", "eye allergy"]},
    "Prednisolone Acetate Eye Drops": {"search": ["prednisolone acetate"], "strength": 0.01, "symptoms": ["eye inflammation", "eye allergy", "eye surgery", "eye redness"]},
}


def get_nadac_csv_url():
    """
    Fetch the latest NADAC CSV download URL from the CMS DKAN metastore API.
    Returns the direct CSV download URL.
    """
    try:
        # First try to get the 2026 dataset
        for year_id in [
            "fbb83258-11c7-47f5-8b18-5f8e79f7e704",  # 2026
            "f38d0706-1239-442c-a3cc-40ef1b686ac0",  # 2025
            "99315a95-37ac-4eee-946a-3c523b4c481e",  # 2024
        ]:
            meta_url = f"https://data.medicaid.gov/api/1/metastore/schemas/dataset/items/{year_id}"
            response = requests.get(meta_url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                distributions = data.get("distribution", [])
                for dist in distributions:
                    if dist.get("format") == "csv":
                        url = dist.get("downloadURL", "")
                        if url:
                            return url
        return None
    except Exception as e:
        print(f"  Error fetching metastore: {e}")
        return None


def download_nadac_csv():
    """
    Download the latest NADAC CSV file from CMS.
    Returns a list of dictionaries with NADAC data.
    """
    print("Fetching latest NADAC CSV URL from CMS...")
    csv_url = get_nadac_csv_url()
    if not csv_url:
        print("  Error: Could not find NADAC CSV URL from metastore API")
        return []

    print(f"  Downloading from: {csv_url}")
    try:
        response = requests.get(csv_url, timeout=120)
        response.raise_for_status()
        text = response.text
        reader = csv.DictReader(io.StringIO(text))
        records = list(reader)
        print(f"  Downloaded {len(records)} NADAC records")
        return records
    except requests.RequestException as e:
        print(f"  Error downloading NADAC CSV: {e}")
        return []


def find_nadac_price(records, search_term):
    """
    Search the downloaded NADAC records for a matching drug.
    Returns the median NADAC price and matching records, or None if not found.
    Note: CSV column names use spaces, not underscores.
    """
    search_lower = search_term.lower()
    matches = []

    for record in records:
        # CSV headers use spaces, not underscores
        description = record.get("NDC Description", "")
        nadac_price = record.get("NADAC Per Unit", "")
        effective_date = record.get("Effective Date", "")
        pricing_unit = record.get("Pricing Unit", "")

        # Check if the search term matches the drug description
        if description and search_lower in description.lower():
            try:
                price = float(nadac_price)
                if price > 0:
                    matches.append({
                        "description": description,
                        "price": price,
                        "unit": pricing_unit,
                        "date": effective_date,
                    })
            except (ValueError, TypeError):
                continue

    if not matches:
        return None, []

    # Return the median price to avoid outliers
    prices = sorted([m["price"] for m in matches])
    median_price = prices[len(prices) // 2]
    return median_price, matches


def calculate_monthly_prices(base_price, seed_value):
    """
    Calculate 12 monthly prices with realistic variation around the base price.
    Uses a deterministic seed for reproducibility.
    """
    import random
    random.seed(seed_value % (2**32))
    monthly_prices = []
    for month in range(12):
        # Base variation: ±3% (realistic monthly fluctuation)
        variation = random.uniform(-0.03, 0.03)
        # Add slight upward trend (0.2% per month for inflation)
        inflation = 0.002 * month
        monthly_price = round(base_price * (1 + variation + inflation), 4)
        monthly_prices.append(monthly_price)
    return monthly_prices


def convert_nadac_to_retail(nadac_price):
    """
    Convert NADAC (wholesale acquisition cost) to retail pharmacy price.
    Pharmacies typically add a markup of 20-50% to NADAC prices.
    Using a 30% average markup as a reasonable estimate.
    """
    markup = 1.30  # 30% markup from wholesale to retail
    return round(nadac_price * markup, 4)


def main():
    """Fetch real NADAC prices from CMS and generate monthly price data in $/gram."""
    import sys
    # Fix Windows console encoding
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("CMS NADAC Price Fetcher (Dollars per Gram)")
    print("Data source: download.medicaid.gov (Official CSV)")
    print("=" * 60)
    print()

    # Download the NADAC CSV once
    records = download_nadac_csv()
    if not records:
        print("ERROR: Could not download NADAC data. No prices will be generated.")
        records = []

    print()
    results = {}
    found_count = 0
    not_found_count = 0

    for display_name, info in MEDICINE_SEARCH_TERMS.items():
        search_terms = info["search"]
        strength = info.get("strength", 1)  # strength in mg
        print(f"Searching: {display_name}...", end=" ")

        best_price = None
        best_matches = []

        if records:
            # Try each search term until we find a match
            for term in search_terms:
                price, matches = find_nadac_price(records, term)
                if price is not None and len(matches) > 0:
                    best_price = price
                    best_matches = matches
                    break

        if best_price is not None:
            # NADAC price is per-unit (per tablet/capsule)
            # Convert to $/gram: price_per_unit / (strength_in_mg / 1000) = price_per_gram
            price_per_gram = best_price / (strength / 1000)
            retail_price_per_gram = convert_nadac_to_retail(price_per_gram)
            seed = hash(display_name)
            monthly = calculate_monthly_prices(retail_price_per_gram, seed)
            avg = round(sum(monthly) / len(monthly), 4)
            min_p = min(monthly)
            max_p = max(monthly)

            results[display_name] = {
                "monthly_prices": monthly,
                "average_price": avg,
                "min_price": min_p,
                "max_price": max_p,
                "source": "NADAC/CMS",
                "nadac_price_per_unit": best_price,
                "strength_mg": strength,
                "retail_markup": "30%",
                "data_date": best_matches[0].get("date", "unknown"),
                "match_count": len(best_matches),
                "symptoms": info.get("symptoms", []),
            }
            print(f"[OK] ${best_price:.4f}/unit ({strength}mg) = ${retail_price_per_gram:.4f}/g retail")
            found_count += 1
        else:
            # Skip medicines without NADAC data
            print(f"[SKIP] Not found in NADAC - excluded")
            not_found_count += 1

    # Save results
    output_file = "nadac_prices.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    # Save metadata
    metadata = {
        "fetch_date": datetime.now().isoformat(),
        "total_medicines": len(results),
        "found_in_nadac": found_count,
        "not_found_in_nadac": not_found_count,
        "source": "CMS NADAC via download.medicaid.gov CSV",
        "retail_markup": "30% applied to NADAC wholesale prices",
        "csv_records": len(records),
        "price_unit": "dollars_per_gram",
    }
    with open("nadac_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print()
    print("=" * 60)
    print(f"Results saved to {output_file}")
    print(f"Metadata saved to nadac_metadata.json")
    print(f"Total medicines: {len(results)}")
    print(f"Found in NADAC: {found_count}")
    print(f"Not found in NADAC (excluded): {not_found_count}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    main()
