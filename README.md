# Auto Problem Solver 🤖
An intelligent automated system that recursively solves programming problems by scraping webpages, generating Python code, executing solutions, and submitting answers to problem endpoints.

---

## Overview
This project uses AI-powered automation to:

- Scrape problem statements from web pages
- Generate Python code to solve the problems
- Execute the code with proper file handling
- Submit answers to specified endpoints
- Automatically chain through multiple problems when new URLs are provided

---

## Features
- **Web Scraping** – Powered by Playwright  
- **AI-Generated Code** – Dynamically creates Python solutions  
- **Secure Execution** – Sandboxed runtime with file support  
- **Recursive Solving** – Follows and processes linked problems  
- **REST API** – Flask server with multiple endpoints  
- **CORS Support** – Ready for integration with any frontend  

---

## API Endpoints

### Main Endpoint
`POST /`  
Solves problems recursively.

#### Request Body:
```json
{
  "email": "student@example.com",
  "secret": "your_secret",
  "url": "https://example.com/problem",
  "max_depth": 20
}
