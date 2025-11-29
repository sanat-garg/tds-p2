from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
import requests
import subprocess
import tempfile
import os
import sys
from pathlib import Path
import shutil
import base64
from urllib.parse import urlparse
import json

AIPIPE_URL = "https://aipipe.org/openrouter/v1/chat/completions"
AIPIPE_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjIzZjIwMDAyOTRAZHMuc3R1ZHkuaWl0bS5hYy5pbiJ9.w3NOcTe8LdMoADPZwP8vKrimps5Y5jVeKZaboYmHkcQ"

# Student secrets database (in production, use a proper database)
secretgiven = "sanat123"

app = Flask(__name__)
CORS(app)

def scrape(url):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.goto(url, wait_until="networkidle")
        html = pg.content()
        b.close()
        return html

def ask_aipipe(html):
    body = {
        "model": "gpt-5-nano",
        "messages": [{"role": "user", "content": '''you will receive a html question page content- and your task is to return a json consisting- {"problem_statement":"","attachments":{},"json_payload":{},"url_endpoint":"","expected_answer_format":""} make sure of these things- 1. return nothing except json- no pretext, no explanation, nothing other than json.  2. briefly describe the task to be done on question page content provided. no need to mention that answer is to be submitted or formatted in json later on. just explain the required task without mentioning about submitting. mention the expected output format also in the problem statement. dont mention attachment's url in problem statement. 3. list attachments mentioned on page in dictionary by assigning a name as key and its url as value. for example - {"data.csv":"https://xyz.com/data.csv","sample.png":"https://example.com/sample.png"} (don't include url endpoint in attachments) 4. json payload is given in content, keep it as it is in json format 5. url endpoint is given in content. 6. excepted answer format could be boolean, number, string, base64 URI of a file attachment, or a JSON object with a combination of these. so make it best suited according to given problem statement. HTML:\n\n'''+html}]}
    headers = {"Authorization": f"Bearer {AIPIPE_KEY}", "Content-Type": "application/json"}
    r = requests.post(AIPIPE_URL, json=body, headers=headers).json()
    if "choices" not in r: return {"aipipe_error": r}
    content = r["choices"][0]["message"]["content"]
    try: return json.loads(content)
    except: return {"raw_text": content}

def gen_code_and_payload(task, original_json_payload, email, secret, url):
    """Generate code and also return the formatted submission payload in one LLM call"""
    prompt = f"""
Act as a programmer who is master at writing problem-solving code. 

TASK: {task}

ORIGINAL JSON PAYLOAD STRUCTURE (preserve this exact structure):
{json.dumps(original_json_payload, indent=2)}

ADDITIONAL INFO:
- email: {email}
- secret: {secret}
- url: {url}

REQUIREMENTS:

1. Write Python code to solve the task:
   - Code MUST run without errors
   - Code should print ONLY the final answer in the expected format
   - Print nothing else except the answer
   - Code should be simple, using simple libraries (if needed)

2. Create the final submission payload:
   - Use the EXACT same structure as the original JSON payload
   - Add these required fields: email, secret, url, correct_answer
   - For correct_answer, use the value that your code will output
   - Preserve all original fields from the payload
   - The correct_answer should be formatted according to the expected answer format

Return ONLY a JSON with these keys:
- python_code: the Python code to solve the problem
- additional_libraries: list of libraries needed to be installed using pip
- submission_payload: the complete JSON payload ready for submission

Return ONLY the JSON, no explanations or other text.
"""
    
    r = requests.post(AIPIPE_URL,
        headers={"Authorization": f"Bearer {AIPIPE_KEY}", "Content-Type": "application/json"},
        json={
            "model": "gpt-5-nano",
            "messages": [{"role": "user", "content": prompt}]
        })
    j = r.json()
    if "choices" not in j: return f"LLM Error: {j}"
    return j["choices"][0]["message"]["content"]

def submit_answer(endpoint_url, payload):
    """Submit the final payload to the endpoint"""
    try:
        response = requests.post(
            endpoint_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        return {
            "success": True,
            "status_code": response.status_code,
            "response_text": response.text,
            "response_json": response.json() if response.headers.get('content-type') == 'application/json' else None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def escape(code):
    code = code.encode().decode('unicode_escape')
    code = code.replace('\\n\\n', '\n\n').replace('\\n', '\n').replace('\\t', '\t')
    import re
    string_pattern = r'(\"\"\"[^\"]*?\"\"\"|\'\'\'[^\']*?\'\'\'|\"[^\"]*?\"|\'[^\']*?\')'
    def restore_escapes(match):
        string_content = match.group(1)
        restored = string_content.replace('\n', '\\n').replace('\t', '\\t')
        return restored
    code = re.sub(string_pattern, restore_escapes, code, flags=re.DOTALL)
    return code

def download_file_from_url(url, custom_filename=None, timeout=10):
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        if custom_filename:
            filename = custom_filename
        else:
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path) or "downloaded_file"
            if '.' not in filename:
                content_type = response.headers.get('content-type', '')
                if 'text/plain' in content_type: filename += '.txt'
                elif 'application/json' in content_type: filename += '.json'
                elif 'image/jpeg' in content_type: filename += '.jpg'
                elif 'image/png' in content_type: filename += '.png'
        return filename, response.content, 'base64'
    except Exception as e:
        raise Exception(f"Failed to download from URL {url}: {str(e)}")

class CodeExecutor:
    def __init__(self, timeout=10):
        self.timeout = timeout
        self.work_dir = None

    def install_libraries(self, libraries):
        if not libraries: return True, ""
        try:
            cmd = [sys.executable, "-m", "pip", "install", "--user"] + libraries
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return (True, result.stdout) if result.returncode == 0 else (False, result.stderr)
        except Exception as e: return False, str(e)

    def setup_work_directory(self, files):
        try:
            self.work_dir = tempfile.mkdtemp()
            saved_files = []
            for file_info in files:
                filename = file_info.get('filename')
                content = file_info.get('content')
                encoding = file_info.get('encoding', 'utf-8')
                url = file_info.get('url')
                
                if url:
                    custom_filename = file_info.get('filename')
                    filename, content, encoding = download_file_from_url(url, custom_filename)
                
                if not filename or content is None: continue
                
                file_path = os.path.join(self.work_dir, filename)
                if encoding == 'base64':
                    file_content = base64.b64decode(content) if isinstance(content, str) else content
                    with open(file_path, 'wb') as f: f.write(file_content)
                else:
                    with open(file_path, 'w', encoding=encoding) as f: f.write(content)
                saved_files.append(filename)
            return True, "", saved_files
        except Exception as e: return False, str(e), []

    def execute_code(self, code):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            code_with_context = f"""
import os
import sys
WORK_DIR = r'{self.work_dir}'
os.chdir(WORK_DIR)
{escape(code)}
""" if self.work_dir else escape(code)
            f.write(code_with_context)
            temp_file = f.name
        
        try:
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True, text=True, timeout=self.timeout, cwd=self.work_dir
            )
            created_files = os.listdir(self.work_dir) if self.work_dir and os.path.exists(self.work_dir) else []
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'code': escape(code),
                'returncode': result.returncode,
                'created_files': created_files
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'stdout': '', 'stderr': f'Execution timed out after {self.timeout} seconds', 'code': escape(code), 'returncode': -1, 'created_files': []}
        except Exception as e:
            return {'success': False, 'code': escape(code), 'stdout': '', 'stderr': str(e), 'returncode': -1, 'created_files': []}
        finally:
            try: os.unlink(temp_file)
            except: pass

    def cleanup(self):
        if self.work_dir and os.path.exists(self.work_dir):
            try: shutil.rmtree(self.work_dir)
            except: pass

def execute_code_with_files(code, libraries, files, timeout=10):
    executor = None
    try:
        executor = CodeExecutor(timeout=timeout)
        
        if files:
            success, error, saved_files = executor.setup_work_directory(files)
            if not success: return {'success': False, 'error': f'Failed to setup files: {error}'}
        
        install_output = ""
        if libraries:
            success, output = executor.install_libraries(libraries)
            install_output = output
            if not success: return {'success': False, 'error': 'Failed to install libraries', 'install_output': output}
        
        result = executor.execute_code(escape(code))
        result['terminal'] = install_output
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        if executor: executor.cleanup()

def solve_problem(url, email, secret, max_depth=20, current_depth=0):
    """Recursive function to solve problems and follow new URLs"""
    if current_depth >= max_depth:
        return {"error": "Maximum recursion depth reached", "current_depth": current_depth}
    
    try:
        print(f"Solving problem at depth {current_depth}: {url}")
        
        # Step 1: Scrape the URL
        html_content = scrape(url)
        scraped_data = ask_aipipe(html_content)
        
        if "aipipe_error" in scraped_data or "raw_text" in scraped_data:
            return {"error": "Failed to parse problem", "details": scraped_data}
        
        # Step 2: Generate code AND submission payload in one LLM call
        task_description = f"{scraped_data['problem_statement']}. Attachments: {list(scraped_data['attachments'].keys())}"
        code_and_payload_result = gen_code_and_payload(
            task=task_description,
            original_json_payload=scraped_data.get('json_payload', {}),
            email=email,
            secret=secret,
            url=url
        )
        
        try:
            code_data = json.loads(code_and_payload_result)
            python_code = code_data.get("python_code")
            additional_libraries = code_data.get("additional_libraries", [])
            submission_payload = code_data.get("submission_payload", {})
        except Exception as e:
            return {"error": "Failed to generate valid code and payload", "code_output": code_and_payload_result}
        
        # Step 3: Prepare files for execution
        files = []
        for filename, file_url in scraped_data['attachments'].items():
            files.append({
                "filename": filename,
                "url": file_url
            })
        
        # Step 4: Execute code
        execution_result = execute_code_with_files(
            code=python_code,
            libraries=additional_libraries,
            files=files,
            timeout=30
        )
        
        if not execution_result.get('success'):
            return {
                "error": "Code execution failed",
                "execution_result": execution_result
            }
        
        final_answer = execution_result.get('stdout', '').strip()
        print(f"Computed answer at depth {current_depth}: {final_answer}")
        
        # Update the submission payload with the actual computed answer
        if submission_payload and 'correct_answer' in submission_payload:
            submission_payload['correct_answer'] = final_answer
        
        if submission_payload and 'final_answer' in submission_payload:
            submission_payload['final_answer'] = final_answer
        
        if submission_payload and 'answer' in submission_payload:
            submission_payload['answer'] = final_answer
        
        # Ensure required fields are present
        submission_payload['email'] = email
        submission_payload['secret'] = secret
        submission_payload['url'] = url
        
        # Step 5: Submit to endpoint
        endpoint_url = scraped_data.get('url_endpoint', '')
        print(f"Submitting to endpoint: {endpoint_url}")
        submission_result = submit_answer(endpoint_url, submission_payload)
        
        result = {
            "success": True,
            "current_depth": current_depth,
            "submission": submission_payload,
            "final_answer": final_answer,
            "submission_result": submission_result
        }
        
        # Check if we need to solve another problem
        if (submission_result.get('success') and 
            submission_result.get('status_code') == 200):
            
            response_data = submission_result.get('response_json', {})
            
            # If new URL provided in response, solve the next problem
            if response_data and response_data.get('url'):
                next_url = response_data['url']
                print(f"Next URL detected at depth {current_depth}: {next_url}")
                
                result["next_problem_detected"] = True
                result["next_url"] = next_url
                
                # Recursively solve the next problem
                next_result = solve_problem(
                    url=next_url,
                    email=email,  # Use same email
                    secret=secret,  # Use same secret
                    max_depth=max_depth,
                    current_depth=current_depth + 1
                )
                result["next_problem_result"] = next_result
                
            else:
                result["next_problem_detected"] = False
                if response_data:
                    result["answer_correct"] = response_data.get('correct')
                    result["reason"] = response_data.get('reason')
                    
        return result
        
    except Exception as e:
        print(f"Error at depth {current_depth}: {str(e)}")
        return {"error": str(e), "current_depth": current_depth}

@app.route("/", methods=["POST"])
def main_endpoint():
    # Validate request
    if not request.json:
        return jsonify({"error": "Invalid JSON"}), 400
    
    email = request.json.get("email")
    secret = request.json.get("secret")
    url = request.json.get("url")
    max_depth = request.json.get("max_depth", 20)  # Allow configuring max recursion depth
    
    if not all([email, secret, url]):
        return jsonify({"error": "Missing required fields: email, secret, url"}), 400
    
    # Validate secret
    if secretgiven != secret:
        return jsonify({"error": "Invalid secret"}), 403
    
    try:
        # Start the recursive problem solving
        result = solve_problem(url, email, secret, max_depth=max_depth)
        
        if "error" in result:
            return jsonify(result), 500
            
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Keep existing endpoints for backward compatibility
@app.route("/scrape", methods=["POST"])
def run_scrape():
    url = request.json.get("url")
    if not url: return jsonify({"error": "url required"}), 400
    try: return jsonify(ask_aipipe(scrape(url)))
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.post("/generate")
def generate():
    data = request.get_json()
    if not data: return jsonify({"error": "Invalid JSON"}), 400
    task = f"{data['problem_statement']}. Attachments: {data['attachments'].keys()}"
    return jsonify(gen_code_and_payload(task))

@app.route('/execute', methods=['POST'])
def execute():
    data = request.get_json()
    if not data: return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
    
    code = data.get('code')
    if not code: return jsonify({'success': False, 'error': 'No code provided'}), 400
    
    libraries = data.get('libraries', [])
    timeout = data.get('timeout', 10)
    files = data.get('files', [])
    
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 60:
        return jsonify({'success': False, 'error': 'Timeout must be a number between 0 and 60 seconds'}), 400
    
    result = execute_code_with_files(code, libraries, files, timeout)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)