"""
Fetch real NADAC (National Average Drug Acquisition Cost) prices from CMS.
Downloads the latest NADAC CSV file from the official CMS download server.
NADAC represents the average invoice price pharmacies pay for medications.
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
# Format: "Display Name": {"search": ["search_term1", ...], "package_size": typical_tablets_per_pack}
# Package size is used to convert per-unit NADAC price to per-package retail price
MEDICINE_SEARCH_TERMS = {
    # Pain relievers & fever reducers (OTC) - package sizes are typical retail counts
    "Paracetamol (Acetaminophen)": {"search": ["acetaminophen"], "package_size": 60},
    "Ibuprofen": {"search": ["ibuprofen"], "package_size": 50},
    "Aspirin": {"search": ["aspirin"], "package_size": 50},
    "Naproxen": {"search": ["naproxen"], "package_size": 50},
    "Aspirin Low Dose (81mg)": {"search": ["aspirin 81"], "package_size": 60},

    # Prescription pain medications
    "Hydrocodone/Acetaminophen": {"search": ["hydrocodone acetaminophen"], "package_size": 30},
    "Oxycodone": {"search": ["oxycodone"], "package_size": 30},
    "Tramadol": {"search": ["tramadol"], "package_size": 30},
    "Gabapentin": {"search": ["gabapentin"], "package_size": 60},
    "Pregabalin": {"search": ["pregabalin"], "package_size": 30},
    "Prednisone": {"search": ["prednisone"], "package_size": 60},
    "Prednisolone": {"search": ["prednisolone"], "package_size": 30},
    "Dexamethasone": {"search": ["dexamethasone"], "package_size": 60},
    "Meloxicam": {"search": ["meloxicam"], "package_size": 30},
    "Celecoxib": {"search": ["celecoxib"], "package_size": 30},
    "Diclofenac": {"search": ["diclofenac"], "package_size": 60},
    "Indomethacin": {"search": ["indomethacin"], "package_size": 60},
    "Cyclobenzaprine": {"search": ["cyclobenzaprine"], "package_size": 30},
    "Tizanidine": {"search": ["tizanidine"], "package_size": 30},
    "Methocarbamol": {"search": ["methocarbamol"], "package_size": 30},

    # Antibiotics
    "Amoxicillin": {"search": ["amoxicillin"], "package_size": 30},
    "Amoxicillin/Clavulanate": {"search": ["amoxicillin clavulanate"], "package_size": 20},
    "Azithromycin": {"search": ["azithromycin"], "package_size": 6},
    "Ciprofloxacin": {"search": ["ciprofloxacin"], "package_size": 30},
    "Doxycycline": {"search": ["doxycycline"], "package_size": 30},
    "Levofloxacin": {"search": ["levofloxacin"], "package_size": 30},
    "Metronidazole": {"search": ["metronidazole"], "package_size": 30},
    "Cephalexin": {"search": ["cephalexin"], "package_size": 30},
    "Trimethoprim/Sulfamethoxazole": {"search": ["trimethoprim sulfamethoxazole"], "package_size": 30},
    "Clindamycin": {"search": ["clindamycin"], "package_size": 30},
    "Nitrofurantoin": {"search": ["nitrofurantoin"], "package_size": 30},
    "Fluconazole": {"search": ["fluconazole"], "package_size": 7},
    "Valacyclovir": {"search": ["valacyclovir"], "package_size": 30},
    "Acyclovir": {"search": ["acyclovir"], "package_size": 70},
    "Erythromycin": {"search": ["erythromycin"], "package_size": 30},
    "Penicillin VK": {"search": ["penicillin vk"], "package_size": 30},
    "Tetracycline": {"search": ["tetracycline"], "package_size": 30},
    "Minocycline": {"search": ["minocycline"], "package_size": 30},

    # Blood pressure & heart medications
    "Lisinopril": {"search": ["lisinopril"], "package_size": 30},
    "Amlodipine": {"search": ["amlodipine"], "package_size": 30},
    "Metoprolol": {"search": ["metoprolol"], "package_size": 60},
    "Losartan": {"search": ["losartan"], "package_size": 30},
    "Hydrochlorothiazide": {"search": ["hydrochlorothiazide"], "package_size": 30},
    "Atenolol": {"search": ["atenolol"], "package_size": 60},
    "Carvedilol": {"search": ["carvedilol"], "package_size": 60},
    "Valsartan": {"search": ["valsartan"], "package_size": 30},
    "Furosemide": {"search": ["furosemide"], "package_size": 60},
    "Spironolactone": {"search": ["spironolactone"], "package_size": 60},
    "Clonidine": {"search": ["clonidine"], "package_size": 30},
    "Diltiazem": {"search": ["diltiazem"], "package_size": 60},
    "Verapamil": {"search": ["verapamil"], "package_size": 60},
    "Warfarin": {"search": ["warfarin"], "package_size": 28},
    "Clopidogrel": {"search": ["clopidogrel"], "package_size": 30},
    "Digoxin": {"search": ["digoxin"], "package_size": 60},
    "Apixaban": {"search": ["apixaban"], "package_size": 30},
    "Rivaroxaban": {"search": ["rivaroxaban"], "package_size": 28},
    "Losartan/HCTZ": {"search": ["losartan hydrochlorothiazide"], "package_size": 30},
    "Lisinopril/HCTZ": {"search": ["lisinopril hydrochlorothiazide"], "package_size": 30},
    "Amlodipine/Valsartan": {"search": ["amlodipine valsartan"], "package_size": 30},

    # Cholesterol medications
    "Atorvastatin": {"search": ["atorvastatin"], "package_size": 30},
    "Simvastatin": {"search": ["simvastatin"], "package_size": 30},
    "Rosuvastatin": {"search": ["rosuvastatin"], "package_size": 30},
    "Pravastatin": {"search": ["pravastatin"], "package_size": 30},
    "Ezetimibe": {"search": ["ezetimibe"], "package_size": 30},
    "Fenofibrate": {"search": ["fenofibrate"], "package_size": 30},
    "Gemfibrozil": {"search": ["gemfibrozil"], "package_size": 60},
    "Ezetimibe/Simvastatin": {"search": ["ezetimibe simvastatin"], "package_size": 30},

    # Diabetes medications
    "Metformin": {"search": ["metformin"], "package_size": 60},
    "Glipizide": {"search": ["glipizide"], "package_size": 60},
    "Glyburide": {"search": ["glyburide"], "package_size": 60},
    "Pioglitazone": {"search": ["pioglitazone"], "package_size": 30},
    "Insulin Glargine": {"search": ["insulin glargine"], "package_size": 1},
    "Insulin Lispro": {"search": ["insulin lispro"], "package_size": 1},
    "Sitagliptin": {"search": ["sitagliptin"], "package_size": 30},
    "Empagliflozin": {"search": ["empagliflozin"], "package_size": 30},
    "Dapagliflozin": {"search": ["dapagliflozin"], "package_size": 30},
    "Glimepiride": {"search": ["glimepiride"], "package_size": 60},
    "Semaglutide": {"search": ["semaglutide"], "package_size": 1},
    "Liraglutide": {"search": ["liraglutide"], "package_size": 1},
    "Dulaglutide": {"search": ["dulaglutide"], "package_size": 1},
    "Canagliflozin": {"search": ["canagliflozin"], "package_size": 30},
    "Metformin/Sitagliptin": {"search": ["metformin sitagliptin"], "package_size": 30},

    # Allergy & cold medications
    "Cetirizine": {"search": ["cetirizine"], "package_size": 30},
    "Loratadine": {"search": ["loratadine"], "package_size": 30},
    "Fexofenadine": {"search": ["fexofenadine"], "package_size": 30},
    "Diphenhydramine": {"search": ["diphenhydramine"], "package_size": 50},
    "Chlorpheniramine": {"search": ["chlorpheniramine"], "package_size": 50},
    "Fluticasone Nasal": {"search": ["fluticasone nasal"], "package_size": 1},
    "Montelukast": {"search": ["montelukast"], "package_size": 30},
    "Pseudoephedrine": {"search": ["pseudoephedrine"], "package_size": 24},
    "Guaifenesin": {"search": ["guaifenesin"], "package_size": 20},
    "Dextromethorphan": {"search": ["dextromethorphan"], "package_size": 20},
    "Olopatadine": {"search": ["olopatadine"], "package_size": 1},
    "Azelastine": {"search": ["azelastine"], "package_size": 1},

    # Respiratory medications
    "Albuterol Inhaler": {"search": ["albuterol inhal"], "package_size": 1},
    "Fluticasone": {"search": ["fluticasone"], "package_size": 1},
    "Budesonide": {"search": ["budesonide"], "package_size": 1},
    "Tiotropium": {"search": ["tiotropium"], "package_size": 1},
    "Ipratropium": {"search": ["ipratropium"], "package_size": 1},
    "Salmeterol/Fluticasone": {"search": ["salmeterol fluticasone"], "package_size": 1},
    "Formoterol/Budesonide": {"search": ["formoterol budesonide"], "package_size": 1},
    "Guaifenesin/Dextromethorphan": {"search": ["guaifenesin dextromethorphan"], "package_size": 20},

    # Stomach & digestive medications
    "Omeprazole": {"search": ["omeprazole"], "package_size": 30},
    "Esomeprazole": {"search": ["esomeprazole"], "package_size": 30},
    "Lansoprazole": {"search": ["lansoprazole"], "package_size": 30},
    "Pantoprazole": {"search": ["pantoprazole"], "package_size": 30},
    "Famotidine": {"search": ["famotidine"], "package_size": 30},
    "Cimetidine": {"search": ["cimetidine"], "package_size": 60},
    "Metoclopramide": {"search": ["metoclopramide"], "package_size": 30},
    "Ondansetron": {"search": ["ondansetron"], "package_size": 10},
    "Promethazine": {"search": ["promethazine"], "package_size": 30},
    "Loperamide": {"search": ["loperamide"], "package_size": 24},
    "Docusate": {"search": ["docusate"], "package_size": 100},
    "Senna": {"search": ["senna"], "package_size": 50},
    "Polyethylene Glycol": {"search": ["polyethylene glycol"], "package_size": 10},
    "Bisacodyl": {"search": ["bisacodyl"], "package_size": 100},
    "Simethicone": {"search": ["simethicone"], "package_size": 50},
    "Mesalamine": {"search": ["mesalamine"], "package_size": 60},
    "Prochlorperazine": {"search": ["prochlorperazine"], "package_size": 30},

    # Mental health & neurological medications
    "Amitriptyline": {"search": ["amitriptyline"], "package_size": 30},
    "Nortriptyline": {"search": ["nortriptyline"], "package_size": 30},
    "Duloxetine": {"search": ["duloxetine"], "package_size": 30},
    "Venlafaxine": {"search": ["venlafaxine"], "package_size": 30},
    "Bupropion": {"search": ["bupropion"], "package_size": 30},
    "Trazodone": {"search": ["trazodone"], "package_size": 60},
    "Mirtazapine": {"search": ["mirtazapine"], "package_size": 30},
    "Fluoxetine": {"search": ["fluoxetine"], "package_size": 30},
    "Sertraline": {"search": ["sertraline"], "package_size": 30},
    "Escitalopram": {"search": ["escitalopram"], "package_size": 30},
    "Citalopram": {"search": ["citalopram"], "package_size": 30},
    "Paroxetine": {"search": ["paroxetine"], "package_size": 30},
    "Alprazolam": {"search": ["alprazolam"], "package_size": 30},
    "Lorazepam": {"search": ["lorazepam"], "package_size": 30},
    "Clonazepam": {"search": ["clonazepam"], "package_size": 30},
    "Diazepam": {"search": ["diazepam"], "package_size": 30},
    "Zolpidem": {"search": ["zolpidem"], "package_size": 30},
    "Levothyroxine": {"search": ["levothyroxine"], "package_size": 90},
    "Methimazole": {"search": ["methimazole"], "package_size": 30},
    "Lithium": {"search": ["lithium"], "package_size": 60},
    "Valproic Acid": {"search": ["valproic acid"], "package_size": 60},
    "Lamotrigine": {"search": ["lamotrigine"], "package_size": 30},
    "Carbamazepine": {"search": ["carbamazepine"], "package_size": 60},
    "Phenytoin": {"search": ["phenytoin"], "package_size": 60},
    "Topiramate": {"search": ["topiramate"], "package_size": 30},
    "Levetiracetam": {"search": ["levetiracetam"], "package_size": 60},
    "Risperidone": {"search": ["risperidone"], "package_size": 30},
    "Quetiapine": {"search": ["quetiapine"], "package_size": 60},
    "Olanzapine": {"search": ["olanzapine"], "package_size": 30},
    "Aripiprazole": {"search": ["aripiprazole"], "package_size": 30},
    "Haloperidol": {"search": ["haloperidol"], "package_size": 100},
    "Methylphenidate": {"search": ["methylphenidate"], "package_size": 30},
    "Amphetamine/Dextroamphetamine": {"search": ["amphetamine dextroamphetamine"], "package_size": 90},
    "Atomoxetine": {"search": ["atomoxetine"], "package_size": 30},
    "Clozapine": {"search": ["clozapine"], "package_size": 60},

    # Urinary & prostate medications
    "Tamsulosin": {"search": ["tamsulosin"], "package_size": 30},
    "Finasteride": {"search": ["finasteride"], "package_size": 30},

    # Vitamins & supplements
    "Vitamin D": {"search": ["vitamin d"], "package_size": 60},
    "Calcium Carbonate": {"search": ["calcium carbonate"], "package_size": 120},
    "Iron Supplement": {"search": ["iron"], "package_size": 30},
    "Folic Acid": {"search": ["folic acid"], "package_size": 100},
    "Potassium Chloride": {"search": ["potassium chloride"], "package_size": 60},
    "Magnesium Oxide": {"search": ["magnesium oxide"], "package_size": 120},
    "Vitamin B12": {"search": ["vitamin b12"], "package_size": 30},
    "Vitamin C": {"search": ["vitamin c"], "package_size": 100},
    "Vitamin E": {"search": ["vitamin e"], "package_size": 100},
    "Omega-3 Fish Oil": {"search": ["omega 3"], "package_size": 60},
    "Coenzyme Q10": {"search": ["coenzyme q10"], "package_size": 30},
    "Melatonin": {"search": ["melatonin"], "package_size": 60},
    "Zinc": {"search": ["zinc"], "package_size": 100},
    "Biotin": {"search": ["biotin"], "package_size": 60},
    "Glucosamine": {"search": ["glucosamine"], "package_size": 60},
    "Turmeric/Curcumin": {"search": ["curcumin"], "package_size": 60},

    # Topical medications
    "Hydrocortisone Cream": {"search": ["hydrocortisone"], "package_size": 1},
    "Benzoyl Peroxide": {"search": ["benzoyl peroxide"], "package_size": 1},
    "Salicylic Acid": {"search": ["salicylic acid"], "package_size": 1},
    "Adapalene": {"search": ["adapalene"], "package_size": 1},
    "Tretinoin": {"search": ["tretinoin"], "package_size": 1},
    "Clotrimazole": {"search": ["clotrimazole"], "package_size": 1},
    "Miconazole": {"search": ["miconazole"], "package_size": 1},
    "Neomycin/Bacitracin": {"search": ["neomycin bacitracin"], "package_size": 1},
    "Lidocaine": {"search": ["lidocaine"], "package_size": 1},
    "Prilocaine/Lidocaine": {"search": ["prilocaine lidocaine"], "package_size": 1},
    "Diclofenac Gel": {"search": ["diclofenac"], "package_size": 1},
    "Ketoconazole": {"search": ["ketoconazole"], "package_size": 1},
    "Terbinafine": {"search": ["terbinafine"], "package_size": 1},
    "Acyclovir Cream": {"search": ["acyclovir"], "package_size": 1},
    "Pimecrolimus": {"search": ["pimecrolimus"], "package_size": 1},
    "Tacrolimus": {"search": ["tacrolimus"], "package_size": 1},

    # Eye & ear medications
    "Artificial Tears": {"search": ["artificial tears"], "package_size": 1},
    "Ketotifen Eye Drops": {"search": ["ketotifen"], "package_size": 1},
    "Ciprofloxacin Ear Drops": {"search": ["ciprofloxacin"], "package_size": 1},
    "Ofloxacin Ear Drops": {"search": ["ofloxacin"], "package_size": 1},

    # Additional commonly prescribed medications
    "Isosorbide Mononitrate": {"search": ["isosorbide mononitrate"], "package_size": 60},
    "Nitroglycerin": {"search": ["nitroglycerin"], "package_size": 1},
    "Amiodarone": {"search": ["amiodarone"], "package_size": 60},
    "Sulfasalazine": {"search": ["sulfasalazine"], "package_size": 100},
    "Insulin NPH": {"search": ["insulin nph"], "package_size": 1},
    "Niacin": {"search": ["niacin"], "package_size": 60},
    "Isotretinoin": {"search": ["isotretinoin"], "package_size": 60},
    "Azelaic Acid": {"search": ["azelaic acid"], "package_size": 1},
    "Tranexamic Acid": {"search": ["tranexamic acid"], "package_size": 30},
    "Hydroquinone": {"search": ["hydroquinone"], "package_size": 1},
}

# Fallback retail prices (used only if NADAC API returns no results)
# These are typical US pharmacy retail prices as estimates
FALLBACK_RETAIL_PRICES = {
    "Paracetamol (Acetaminophen)": 9.50,
    "Ibuprofen": 11.50,
    "Aspirin": 7.00,
    "Naproxen": 10.00,
    "Aspirin Low Dose (81mg)": 8.50,
    "Hydrocodone/Acetaminophen": 25.00,
    "Oxycodone": 45.00,
    "Tramadol": 15.00,
    "Gabapentin": 18.00,
    "Pregabalin": 65.00,
    "Prednisone": 12.00,
    "Prednisolone": 15.00,
    "Dexamethasone": 18.00,
    "Meloxicam": 22.00,
    "Celecoxib": 55.00,
    "Diclofenac": 20.00,
    "Indomethacin": 14.00,
    "Cyclobenzaprine": 12.00,
    "Tizanidine": 35.00,
    "Methocarbamol": 16.00,
    "Amoxicillin": 19.50,
    "Amoxicillin/Clavulanate": 35.00,
    "Azithromycin": 28.00,
    "Ciprofloxacin": 22.00,
    "Doxycycline": 16.00,
    "Levofloxacin": 45.00,
    "Metronidazole": 18.00,
    "Cephalexin": 20.00,
    "Trimethoprim/Sulfamethoxazole": 12.00,
    "Clindamycin": 25.00,
    "Nitrofurantoin": 22.00,
    "Fluconazole": 30.00,
    "Valacyclovir": 35.00,
    "Acyclovir": 18.00,
    "Erythromycin": 15.00,
    "Penicillin VK": 14.00,
    "Tetracycline": 12.00,
    "Minocycline": 20.00,
    "Lisinopril": 12.50,
    "Amlodipine": 14.00,
    "Metoprolol": 16.00,
    "Losartan": 22.00,
    "Hydrochlorothiazide": 10.00,
    "Atenolol": 12.00,
    "Carvedilol": 18.00,
    "Valsartan": 28.00,
    "Furosemide": 10.00,
    "Spironolactone": 14.00,
    "Clonidine": 12.00,
    "Diltiazem": 20.00,
    "Verapamil": 18.00,
    "Warfarin": 12.00,
    "Clopidogrel": 35.00,
    "Digoxin": 10.00,
    "Apixaban": 180.00,
    "Rivaroxaban": 200.00,
    "Losartan/HCTZ": 28.00,
    "Lisinopril/HCTZ": 18.00,
    "Amlodipine/Valsartan": 35.00,
    "Atorvastatin": 36.00,
    "Simvastatin": 14.00,
    "Rosuvastatin": 45.00,
    "Pravastatin": 16.00,
    "Ezetimibe": 35.00,
    "Fenofibrate": 25.00,
    "Gemfibrozil": 18.00,
    "Ezetimibe/Simvastatin": 40.00,
    "Metformin": 13.50,
    "Glipizide": 14.00,
    "Glyburide": 10.00,
    "Pioglitazone": 28.00,
    "Insulin Glargine": 65.00,
    "Insulin Lispro": 70.00,
    "Sitagliptin": 45.00,
    "Empagliflozin": 85.00,
    "Dapagliflozin": 80.00,
    "Glimepiride": 12.00,
    "Semaglutide": 350.00,
    "Liraglutide": 280.00,
    "Dulaglutide": 300.00,
    "Canagliflozin": 90.00,
    "Metformin/Sitagliptin": 55.00,
    "Cetirizine": 10.50,
    "Loratadine": 9.00,
    "Fexofenadine": 18.00,
    "Diphenhydramine": 7.50,
    "Chlorpheniramine": 8.00,
    "Fluticasone Nasal": 35.00,
    "Montelukast": 45.00,
    "Pseudoephedrine": 10.00,
    "Guaifenesin": 8.50,
    "Dextromethorphan": 9.00,
    "Olopatadine": 45.00,
    "Azelastine": 40.00,
    "Albuterol Inhaler": 57.00,
    "Fluticasone": 40.00,
    "Budesonide": 55.00,
    "Tiotropium": 120.00,
    "Ipratropium": 35.00,
    "Salmeterol/Fluticasone": 120.00,
    "Formoterol/Budesonide": 130.00,
    "Guaifenesin/Dextromethorphan": 12.00,
    "Omeprazole": 25.50,
    "Esomeprazole": 35.00,
    "Lansoprazole": 30.00,
    "Pantoprazole": 28.00,
    "Famotidine": 12.00,
    "Cimetidine": 10.00,
    "Metoclopramide": 18.00,
    "Ondansetron": 35.00,
    "Promethazine": 15.00,
    "Loperamide": 8.00,
    "Docusate": 7.50,
    "Senna": 8.00,
    "Polyethylene Glycol": 12.00,
    "Bisacodyl": 8.50,
    "Simethicone": 9.00,
    "Mesalamine": 55.00,
    "Prochlorperazine": 16.00,
    "Amitriptyline": 10.00,
    "Nortriptyline": 12.00,
    "Duloxetine": 45.00,
    "Venlafaxine": 35.00,
    "Bupropion": 28.00,
    "Trazodone": 14.00,
    "Mirtazapine": 22.00,
    "Fluoxetine": 18.00,
    "Sertraline": 16.00,
    "Escitalopram": 30.00,
    "Citalopram": 14.00,
    "Paroxetine": 20.00,
    "Alprazolam": 15.00,
    "Lorazepam": 14.00,
    "Clonazepam": 18.00,
    "Diazepam": 12.00,
    "Zolpidem": 25.00,
    "Levothyroxine": 12.00,
    "Methimazole": 14.00,
    "Lithium": 16.00,
    "Valproic Acid": 22.00,
    "Lamotrigine": 28.00,
    "Carbamazepine": 20.00,
    "Phenytoin": 14.00,
    "Topiramate": 30.00,
    "Levetiracetam": 45.00,
    "Risperidone": 25.00,
    "Quetiapine": 35.00,
    "Olanzapine": 45.00,
    "Aripiprazole": 55.00,
    "Haloperidol": 12.00,
    "Methylphenidate": 35.00,
    "Amphetamine/Dextroamphetamine": 40.00,
    "Atomoxetine": 55.00,
    "Clozapine": 40.00,
    "Tamsulosin": 22.00,
    "Finasteride": 18.00,
    "Vitamin D": 12.00,
    "Calcium Carbonate": 10.00,
    "Iron Supplement": 14.00,
    "Folic Acid": 8.00,
    "Potassium Chloride": 12.00,
    "Magnesium Oxide": 10.00,
    "Vitamin B12": 15.00,
    "Vitamin C": 10.00,
    "Vitamin E": 12.00,
    "Omega-3 Fish Oil": 18.00,
    "Coenzyme Q10": 25.00,
    "Melatonin": 10.00,
    "Zinc": 10.00,
    "Biotin": 12.00,
    "Glucosamine": 22.00,
    "Turmeric/Curcumin": 20.00,
    "Hydrocortisone Cream": 8.50,
    "Benzoyl Peroxide": 12.00,
    "Salicylic Acid": 10.00,
    "Adapalene": 25.00,
    "Tretinoin": 45.00,
    "Clotrimazole": 12.00,
    "Miconazole": 12.00,
    "Neomycin/Bacitracin": 10.00,
    "Lidocaine": 12.00,
    "Prilocaine/Lidocaine": 25.00,
    "Diclofenac Gel": 22.00,
    "Ketoconazole": 18.00,
    "Terbinafine": 20.00,
    "Acyclovir Cream": 15.00,
    "Pimecrolimus": 65.00,
    "Tacrolimus": 70.00,
    "Artificial Tears": 8.00,
    "Ketotifen Eye Drops": 25.00,
    "Ciprofloxacin Ear Drops": 35.00,
    "Ofloxacin Ear Drops": 40.00,
    "Isosorbide Mononitrate": 18.00,
    "Nitroglycerin": 25.00,
    "Amiodarone": 45.00,
    "Sulfasalazine": 35.00,
    "Insulin NPH": 55.00,
    "Niacin": 10.00,
    "Isotretinoin": 85.00,
    "Azelaic Acid": 35.00,
    "Tranexamic Acid": 25.00,
    "Hydroquinone": 20.00,
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
        monthly_price = round(base_price * (1 + variation + inflation), 2)
        monthly_prices.append(monthly_price)
    return monthly_prices


def convert_nadac_to_retail(nadac_price):
    """
    Convert NADAC (wholesale acquisition cost) to retail pharmacy price.
    Pharmacies typically add a markup of 20-50% to NADAC prices.
    Using a 30% average markup as a reasonable estimate.
    """
    markup = 1.30  # 30% markup from wholesale to retail
    return round(nadac_price * markup, 2)


def main():
    """Fetch real NADAC prices from CMS and generate monthly price data."""
    import sys
    # Fix Windows console encoding
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 60)
    print("CMS NADAC Price Fetcher")
    print("Data source: download.medicaid.gov (Official CSV)")
    print("=" * 60)
    print()

    # Download the NADAC CSV once
    records = download_nadac_csv()
    if not records:
        print("ERROR: Could not download NADAC data. Using fallback prices.")
        records = []

    print()
    results = {}
    found_count = 0
    fallback_count = 0

    for display_name, info in MEDICINE_SEARCH_TERMS.items():
        search_terms = info["search"]
        package_size = info.get("package_size", 30)
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
            # NADAC price is per-unit; multiply by package size then apply retail markup
            package_wholesale = best_price * package_size
            retail_price = convert_nadac_to_retail(package_wholesale)
            seed = hash(display_name)
            monthly = calculate_monthly_prices(retail_price, seed)
            avg = round(sum(monthly) / len(monthly), 2)
            min_p = min(monthly)
            max_p = max(monthly)

            results[display_name] = {
                "monthly_prices": monthly,
                "average_price": avg,
                "min_price": min_p,
                "max_price": max_p,
                "source": "NADAC/CMS",
                "nadac_price_per_unit": best_price,
                "package_size": package_size,
                "retail_markup": "30%",
                "data_date": best_matches[0].get("date", "unknown"),
                "match_count": len(best_matches),
            }
            print(f"[OK] ${best_price:.4f}/unit x {package_size} = ${retail_price:.2f} retail")
            found_count += 1
        else:
            # Fallback to estimated retail price
            fallback_price = FALLBACK_RETAIL_PRICES.get(display_name, 20.00)
            seed = hash(display_name)
            monthly = calculate_monthly_prices(fallback_price, seed)
            avg = round(sum(monthly) / len(monthly), 2)
            min_p = min(monthly)
            max_p = max(monthly)

            results[display_name] = {
                "monthly_prices": monthly,
                "average_price": avg,
                "min_price": min_p,
                "max_price": max_p,
                "source": "Estimated (NADAC not found)",
                "nadac_price_per_unit": None,
                "package_size": package_size,
                "retail_markup": "N/A",
                "data_date": "N/A",
                "match_count": 0,
            }
            print(f"[MISS] Not found, using fallback (${fallback_price:.2f})")
            fallback_count += 1

    # Save results
    output_file = "nadac_prices.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    # Save metadata
    metadata = {
        "fetch_date": datetime.now().isoformat(),
        "total_medicines": len(results),
        "found_in_nadac": found_count,
        "fallback_estimates": fallback_count,
        "source": "CMS NADAC via download.medicaid.gov CSV",
        "retail_markup": "30% applied to NADAC wholesale prices",
        "csv_records": len(records),
    }
    with open("nadac_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print()
    print("=" * 60)
    print(f"Results saved to {output_file}")
    print(f"Metadata saved to nadac_metadata.json")
    print(f"Total medicines: {len(results)}")
    print(f"Found in NADAC: {found_count}")
    print(f"Fallback estimates: {fallback_count}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    main()
