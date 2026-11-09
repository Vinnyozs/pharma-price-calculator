import json
import os
import re
import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)
app.jinja_env.auto_reload = True
app.config['TEMPLATES_AUTO_RELOAD'] = True

months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
]

# Data freshness info
data_date = "Unknown"
nadac_found = 0
nadac_total = 0


def load_medicine_data():
    """Load medicine prices from NADAC JSON file."""
    global data_date, nadac_found, nadac_total

    prices_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nadac_prices.json")
    metadata_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nadac_metadata.json")

    medicines = []

    if os.path.exists(prices_file):
        with open(prices_file, "r") as f:
            prices_data = json.load(f)
        for name, data in prices_data.items():
            medicines.append({
                "name": name,
                "prices": data["monthly_prices"],
            })
            nadac_total += 1
            if data.get("source") == "NADAC/CMS":
                nadac_found += 1
                if data.get("data_date") and data["data_date"] != "N/A":
                    data_date = data["data_date"]

    if os.path.exists(metadata_file):
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        if "fetch_date" in metadata:
            fetch = metadata["fetch_date"][:10]
            if data_date == "Unknown":
                data_date = fetch
            else:
                data_date = "NADAC: {}, Fetched: {}".format(data_date, fetch)

    return medicines


top_medicines = load_medicine_data()


def calculate_averages():
    """Calculate average price for each medicine across all 12 months."""
    averages = []
    for medicine in top_medicines:
        prices = medicine['prices']
        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)
        price_entries = [
            {'month': months[i], 'price': prices[i]}
            for i in range(12)
        ]
        averages.append({
            'name': medicine['name'],
            'average_price': round(avg_price, 2),
            'min_price': round(min_price, 2),
            'max_price': round(max_price, 2),
            'entries': price_entries
        })
    return averages


@app.route('/')
def home():
    averages = calculate_averages()
    return render_template('index.html', averages=averages, months=months,
                           data_date=data_date, nadac_found=nadac_found,
                           nadac_total=nadac_total)


@app.route('/medicine/<int:index>')
def medicine_chart(index):
    if index < 0 or index >= len(top_medicines):
        return render_template('404.html'), 404
    medicine = top_medicines[index]
    prices = medicine['prices']
    avg_price = sum(prices) / len(prices)
    min_price = min(prices)
    max_price = max(prices)
    price_entries = [
        {'month': months[i], 'price': prices[i]}
        for i in range(12)
    ]
    return render_template(
        'chart.html',
        name=medicine['name'],
        months=months,
        entries=price_entries,
        avg_price=round(avg_price, 2),
        min_price=round(min_price, 2),
        max_price=round(max_price, 2),
        data_date=data_date
    )


@app.route('/api/use-case/<path:medicine_name>')
def get_use_case(medicine_name):
    """Fetch a brief use case summary for a medicine using Wikipedia API."""
    from urllib.parse import unquote
    medicine_name = unquote(medicine_name)
    
    # Clean up the medicine name for search (remove parentheticals for search)
    search_name = re.sub(r'\s*\(.*?\)', '', medicine_name).strip()
    
    headers = {
        'User-Agent': 'MedicinePriceApp/1.0 (educational project)'
    }
    
    try:
        # Step 1: Search Wikipedia for the medicine
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            'action': 'query',
            'list': 'search',
            'srsearch': search_name,
            'srlimit': 1,
            'format': 'json',
            'srnamespace': 0,
        }
        
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Check if we found a matching article
        if 'query' not in data or 'search' not in data['query'] or not data['query']['search']:
            return jsonify({"success": False, "error": "No information found for this medicine."}), 404
        
        title = data['query']['search'][0]['title']
        
        # Step 2: Get the extract/summary of the article
        extract_params = {
            'action': 'query',
            'titles': title,
            'prop': 'extracts',
            'exintro': True,
            'explaintext': True,
            'exsentences': 5,
            'format': 'json',
        }
        
        extract_response = requests.get(search_url, params=extract_params, headers=headers, timeout=10)
        extract_response.raise_for_status()
        extract_data = extract_response.json()
        
        pages = extract_data.get('query', {}).get('pages', {})
        page = next(iter(pages.values()))
        extract = page.get('extract', '')
        
        if extract:
            # Clean up the extract
            extract = re.sub(r'\s+', ' ', extract).strip()
            if len(extract) > 500:
                extract = extract[:500].rsplit('.', 1)[0] + '.'
            return jsonify({"success": True, "summary": extract})
        
        return jsonify({"success": False, "error": "Could not fetch use case information for this medicine."}), 404
                
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Request timed out. Please try again."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
