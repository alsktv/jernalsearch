from flask import Flask, render_template, request, jsonify
import time

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/find-references', methods=['POST'])
def find_references():
    try:
        data = request.get_json(silent=True) or request.form
        title = data.get('title') if data else None
        # Simulate an AI search delay
        time.sleep(2)

        if not title:
            return jsonify({'error': '제목이 제공되지 않았습니다.'}), 400

        mock_refs = [
            {"title": "Mock Reference Paper 1", "authors": "John Doe", "year": 2024},
            {"title": "Mock Reference Paper 2", "authors": "Jane Smith", "year": 2025},
            {"title": "Mock Reference Paper 3", "authors": "Alex Brown", "year": 2023}
        ]

        return jsonify({'references': mock_refs})
    except Exception as e:
        # Log exception server-side if desired
        return jsonify({'error': '하위 논문을 찾지 못했습니다.'}), 500

if __name__ == '__main__':
    # Run on port 5002 as requested
    app.run(host='0.0.0.0', port=5002, debug=True)
