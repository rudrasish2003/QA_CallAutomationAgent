from flask import Flask, request, jsonify, render_template_string, redirect, url_for 
import asyncio
import json
from datetime import datetime
import threading
import os
from vapi_analyzer import VAPIAnalyzer, VAPIWebhookHandler

# Create Flask app with proper configuration for Render
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Get API keys from environment variables (required for Render)
VAPI_API_KEY = os.getenv("VAPI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not VAPI_API_KEY or not OPENAI_API_KEY:
    raise ValueError("VAPI_API_KEY and OPENAI_API_KEY environment variables must be set")

# Initialize analyzer
analyzer = VAPIAnalyzer(
    vapi_api_key=VAPI_API_KEY,
    openai_api_key=OPENAI_API_KEY
)
webhook_handler = VAPIWebhookHandler(analyzer)

# Add a default system prompt if none exists
if not analyzer.system_prompts:
    prompt_id = analyzer.add_system_prompt(
        "Default Customer Service",
        """You are a professional customer service agent. Your objectives are:

COMMUNICATION:
- Greet customers warmly and professionally
- Use active listening and acknowledge concerns
- Speak clearly and maintain appropriate pace
- Show empathy and understanding

PROBLEM RESOLUTION:
- Gather all necessary information before proposing solutions
- Provide accurate and helpful information
- Offer multiple options when available
- Follow up to ensure complete resolution

COMPLIANCE:
- Verify customer identity for account inquiries
- Follow data protection protocols
- Document interactions appropriately
- Escalate complex issues when necessary

SUCCESS METRICS:
- First call resolution when possible
- Customer satisfaction and positive experience
- Adherence to company policies
- Professional brand representation"""
    )
    analyzer.activate_prompt(prompt_id)

# HTML Templates
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VAPI Call Analysis Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-gray-800 mb-8">VAPI Call Analysis Dashboard</h1>
        
        <!-- Navigation -->
        <div class="mb-8">
            <nav class="flex space-x-4">
                <a href="/" class="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600">Dashboard</a>
                <a href="/prompts" class="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600">System Prompts</a>
                <a href="/analyses" class="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600">Call Analyses</a>
            </nav>
        </div>

        <!-- Quick Stats -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div class="bg-white rounded-lg shadow-md p-6">
                <h3 class="text-lg font-semibold text-gray-700 mb-2">Active System Prompt</h3>
                <p class="text-sm text-blue-600">{{ active_prompt_name or "No active prompt" }}</p>
            </div>
            <div class="bg-white rounded-lg shadow-md p-6">
                <h3 class="text-lg font-semibold text-gray-700 mb-2">Analyzed Calls</h3>
                <p class="text-3xl font-bold text-green-600">{{ analyzed_count }}</p>
            </div>
            <div class="bg-white rounded-lg shadow-md p-6">
                <h3 class="text-lg font-semibold text-gray-700 mb-2">Average Score</h3>
                <p class="text-3xl font-bold text-purple-600">{{ "%.1f"|format(avg_score) if avg_score else "N/A" }}</p>
            </div>
        </div>

        <!-- Recent Analyses -->
        {% if recent_analyses %}
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Recent Call Analyses</h2>
            <div class="overflow-x-auto">
                <table class="min-w-full table-auto">
                    <thead>
                        <tr class="bg-gray-50">
                            <th class="px-4 py-2 text-left">Call ID</th>
                            <th class="px-4 py-2 text-left">Score</th>
                            <th class="px-4 py-2 text-left">Duration</th>
                            <th class="px-4 py-2 text-left">Analyzed</th>
                            <th class="px-4 py-2 text-left">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for analysis in recent_analyses %}
                        <tr class="border-t">
                            <td class="px-4 py-2 font-mono text-sm">{{ analysis.call_id[:12] }}...</td>
                            <td class="px-4 py-2">
                                <span class="{% if analysis.performance_score >= 8 %}bg-green-100 text-green-800{% elif analysis.performance_score >= 6 %}bg-yellow-100 text-yellow-800{% else %}bg-red-100 text-red-800{% endif %} px-2 py-1 rounded text-sm font-semibold">
                                    {{ "%.1f"|format(analysis.performance_score) }}/10
                                </span>
                            </td>
                            <td class="px-4 py-2 text-sm">{{ analysis.duration }}s</td>
                            <td class="px-4 py-2 text-sm">{{ analysis.analyzed_at[:16] if analysis.analyzed_at else "N/A" }}</td>
                            <td class="px-4 py-2">
                                <button onclick="showAnalysis('{{ analysis.call_id }}')" class="text-blue-500 hover:text-blue-700 text-sm">View Details</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% endif %}

        <!-- Manual Analysis Trigger -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Analyze Recent Calls</h2>
            <p class="text-gray-600 mb-4">Manually trigger analysis of recent calls from VAPI (last 24 hours)</p>
            <button onclick="analyzeRecentCalls()" class="bg-blue-500 text-white px-6 py-3 rounded hover:bg-blue-600 font-semibold">
                Analyze Recent Calls
            </button>
            <div id="analysisStatus" class="mt-4"></div>
        </div>

        <!-- Webhook Info -->
        <div class="bg-blue-50 rounded-lg p-6">
            <h2 class="text-lg font-semibold text-blue-800 mb-2">Webhook Configuration</h2>
            <p class="text-blue-700 mb-2">Configure your VAPI webhook to point to:</p>
            <code class="bg-blue-100 px-3 py-1 rounded text-blue-800">{{ request.url_root }}webhook/vapi</code>
            <p class="text-blue-600 text-sm mt-2">Enable "call-ended" events in your VAPI dashboard</p>
        </div>
    </div>

    <!-- Analysis Modal -->
    <div id="analysisModal" class="fixed inset-0 bg-black bg-opacity-50 hidden z-50">
        <div class="flex items-center justify-center min-h-screen p-4">
            <div class="bg-white rounded-lg max-w-4xl w-full max-h-screen overflow-y-auto">
                <div class="p-6">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="text-xl font-semibold">Call Analysis Details</h3>
                        <button onclick="hideAnalysis()" class="text-gray-500 hover:text-gray-700 text-2xl">&times;</button>
                    </div>
                    <div id="analysisContent"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function analyzeRecentCalls() {
            const statusDiv = document.getElementById('analysisStatus');
            const button = event.target;
            
            button.disabled = true;
            button.innerHTML = 'Analyzing...';
            statusDiv.innerHTML = '<p class="text-blue-600 animate-pulse">Fetching and analyzing recent calls... This may take a few minutes.</p>';
            
            try {
                const response = await fetch('/api/analyze-recent', {
                    method: 'POST'
                });
                const result = await response.json();
                
                if (response.ok) {
                    statusDiv.innerHTML = `<p class="text-green-600">Successfully analyzed ${result.analyzed_calls} calls! <a href="#" onclick="location.reload()" class="text-blue-500 underline">Refresh to see results</a></p>`;
                } else {
                    statusDiv.innerHTML = `<p class="text-red-600">Error: ${result.error}</p>`;
                }
            } catch (error) {
                statusDiv.innerHTML = `<p class="text-red-600">Error: ${error.message}</p>`;
            } finally {
                button.disabled = false;
                button.innerHTML = 'Analyze Recent Calls';
            }
        }

        function showAnalysis(callId) {
            fetch(`/api/analysis/${callId}`)
                .then(response => response.json())
                .then(data => {
                    const modal = document.getElementById('analysisModal');
                    const content = document.getElementById('analysisContent');
                    
                    content.innerHTML = `
                        <div class="space-y-6">
                            <div class="flex justify-between items-center">
                                <div>
                                    <h4 class="text-lg font-semibold">Call ID: ${data.call_id}</h4>
                                    <p class="text-gray-600">Duration: ${data.duration || 'N/A'}s</p>
                                </div>
                                <div class="text-center">
                                    <div class="text-3xl font-bold ${data.performance_score >= 8 ? 'text-green-600' : data.performance_score >= 6 ? 'text-yellow-600' : 'text-red-600'}">${data.performance_score.toFixed(1)}</div>
                                    <div class="text-gray-600">out of 10</div>
                                </div>
                            </div>
                            
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div class="bg-green-50 rounded-lg p-4">
                                    <h5 class="font-semibold text-green-800 mb-2">Strengths</h5>
                                    <ul class="text-sm text-gray-700 space-y-1">
                                        ${data.strengths.map(s => `<li>• ${s}</li>`).join('')}
                                    </ul>
                                </div>
                                
                                <div class="bg-red-50 rounded-lg p-4">
                                    <h5 class="font-semibold text-red-800 mb-2">Improvement Areas</h5>
                                    <ul class="text-sm text-gray-700 space-y-1">
                                        ${data.improvement_areas.map(a => `<li>• ${a}</li>`).join('')}
                                    </ul>
                                </div>
                            </div>
                            
                            ${data.prompt_suggestions.length > 0 ? `
                            <div class="bg-blue-50 rounded-lg p-4">
                                <h5 class="font-semibold text-blue-800 mb-2">Prompt Suggestions</h5>
                                <ul class="text-sm text-gray-700 space-y-1">
                                    ${data.prompt_suggestions.map(s => `<li>• ${s}</li>`).join('')}
                                </ul>
                            </div>
                            ` : ''}
                            
                            ${data.compliance_issues.length > 0 ? `
                            <div class="bg-orange-50 rounded-lg p-4">
                                <h5 class="font-semibold text-orange-800 mb-2">Compliance Issues</h5>
                                <ul class="text-sm text-gray-700 space-y-1">
                                    ${data.compliance_issues.map(i => `<li>• ${i}</li>`).join('')}
                                </ul>
                            </div>
                            ` : ''}
                            
                            <div class="bg-gray-50 rounded-lg p-4">
                                <h5 class="font-semibold text-gray-800 mb-2">Detailed Analysis</h5>
                                <p class="text-sm text-gray-700 whitespace-pre-wrap">${data.detailed_analysis}</p>
                            </div>
                        </div>
                    `;
                    
                    modal.classList.remove('hidden');
                })
                .catch(error => {
                    alert('Error loading analysis details');
                });
        }

        function hideAnalysis() {
            document.getElementById('analysisModal').classList.add('hidden');
        }

        // Close modal when clicking outside
        document.getElementById('analysisModal').addEventListener('click', function(e) {
            if (e.target === this) {
                hideAnalysis();
            }
        });
    </script>
</body>
</html>
'''

PROMPTS_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>System Prompts - VAPI Analysis</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-gray-800 mb-8">System Prompts Management</h1>
        
        <!-- Navigation -->
        <div class="mb-8">
            <nav class="flex space-x-4">
                <a href="/" class="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600">Dashboard</a>
                <a href="/prompts" class="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600">System Prompts</a>
                <a href="/analyses" class="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600">Call Analyses</a>
            </nav>
        </div>

        <!-- Add New Prompt -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Add New System Prompt</h2>
            <form onsubmit="addPrompt(event)">
                <div class="mb-4">
                    <label for="name" class="block text-sm font-medium text-gray-700 mb-2">Prompt Name</label>
                    <input type="text" id="name" name="name" required 
                           class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                           placeholder="e.g., Customer Service Standard, Sales Agent Guidelines">
                </div>
                <div class="mb-4">
                    <label for="prompt" class="block text-sm font-medium text-gray-700 mb-2">System Prompt</label>
                    <textarea id="prompt" name="prompt" rows="12" required
                              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                              placeholder="Enter your detailed system prompt here..."></textarea>
                </div>
                <button type="submit" class="bg-blue-500 text-white px-6 py-2 rounded hover:bg-blue-600 font-semibold">
                    Save Prompt
                </button>
            </form>
        </div>

        <!-- Existing Prompts -->
        <div class="bg-white rounded-lg shadow-md p-6">
            <h2 class="text-xl font-semibold text-gray-800 mb-4">Existing Prompts</h2>
            <div class="space-y-4" id="promptsList">
                {% for prompt in prompts %}
                <div class="border border-gray-200 rounded-lg p-4 {% if prompt.is_active %}ring-2 ring-green-500 bg-green-50{% endif %}">
                    <div class="flex justify-between items-start mb-2">
                        <h3 class="text-lg font-medium text-gray-800">{{ prompt.name }}</h3>
                        <div class="flex space-x-2">
                            {% if prompt.is_active %}
                            <span class="bg-green-100 text-green-800 px-3 py-1 rounded text-sm font-semibold">Active</span>
                            {% else %}
                            <button onclick="activatePrompt('{{ prompt.id }}')" 
                                    class="bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">
                                Activate
                            </button>
                            {% endif %}
                            <button onclick="deletePrompt('{{ prompt.id }}')" 
                                    class="bg-red-500 text-white px-3 py-1 rounded text-sm hover:bg-red-600">
                                Delete
                            </button>
                        </div>
                    </div>
                    <p class="text-gray-600 text-sm mb-2">Created: {{ prompt.created_at[:16] }}</p>
                    <div class="bg-gray-50 p-3 rounded border">
                        <pre class="text-sm text-gray-700 whitespace-pre-wrap">{{ prompt.prompt }}</pre>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>

    <script>
        async function addPrompt(event) {
            event.preventDefault();
            
            const name = document.getElementById('name').value;
            const prompt = document.getElementById('prompt').value;
            
            try {
                const response = await fetch('/api/prompts', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ name, prompt })
                });
                
                if (response.ok) {
                    location.reload();
                } else {
                    alert('Error adding prompt');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        async function activatePrompt(promptId) {
            try {
                const response = await fetch(`/api/prompts/${promptId}/activate`, {
                    method: 'POST'
                });
                if (response.ok) {
                    location.reload();
                } else {
                    alert('Error activating prompt');
                }
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        async function deletePrompt(promptId) {
            if (confirm('Are you sure you want to delete this prompt?')) {
                try {
                    const response = await fetch(`/api/prompts/${promptId}`, {
                        method: 'DELETE'
                    });
                    if (response.ok) {
                        location.reload();
                    } else {
                        alert('Error deleting prompt');
                    }
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }
        }
    </script>
</body>
</html>
'''

ANALYSES_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Call Analyses - VAPI Analysis</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-gray-800 mb-8">Call Analyses</h1>
        
        <!-- Navigation -->
        <div class="mb-8">
            <nav class="flex space-x-4">
                <a href="/" class="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600">Dashboard</a>
                <a href="/prompts" class="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600">System Prompts</a>
                <a href="/analyses" class="bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600">Call Analyses</a>
            </nav>
        </div>

        {% if analyses %}
        <!-- Summary Stats -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <h3 class="text-lg font-semibold text-gray-700">Total Calls</h3>
                <p class="text-2xl font-bold text-blue-600">{{ analyses|length }}</p>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <h3 class="text-lg font-semibold text-gray-700">Average Score</h3>
                <p class="text-2xl font-bold text-green-600">{{ "%.1f"|format(avg_score) }}</p>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <h3 class="text-lg font-semibold text-gray-700">High Performers</h3>
                <p class="text-2xl font-bold text-purple-600">{{ high_scores }}</p>
            </div>
            <div class="bg-white rounded-lg shadow p-4 text-center">
                <h3 class="text-lg font-semibold text-gray-700">Need Improvement</h3>
                <p class="text-2xl font-bold text-red-600">{{ low_scores }}</p>
            </div>
        </div>

        <!-- Analyses List -->
        <div class="space-y-4">
            {% for analysis in analyses %}
            <div class="bg-white rounded-lg shadow-md p-6">
                <div class="flex justify-between items-start mb-4">
                    <div>
                        <h3 class="text-lg font-semibold text-gray-800">Call ID: {{ analysis.call_id }}</h3>
                        <p class="text-gray-600">Analyzed: {{ analysis.analyzed_at[:16] if analysis.analyzed_at else "N/A" }} | Duration: {{ analysis.duration or 'N/A' }}s</p>
                    </div>
                    <div class="text-center">
                        <span class="text-2xl font-bold {% if analysis.performance_score >= 8 %}text-green-600{% elif analysis.performance_score >= 6 %}text-yellow-600{% else %}text-red-600{% endif %}">
                            {{ "%.1f"|format(analysis.performance_score) }}/10
                        </span>
                    </div>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                    <div>
                        <h4 class="font-semibold text-green-700 mb-2">Strengths ({{ analysis.strengths|length }})</h4>
                        <ul class="text-sm text-gray-700 space-y-1">
                            {% for strength in analysis.strengths[:3] %}
                            <li>• {{ strength }}</li>
                            {% endfor %}
                            {% if analysis.strengths|length > 3 %}
                            <li class="text-gray-500">... and {{ analysis.strengths|length - 3 }} more</li>
                            {% endif %}
                        </ul>
                    </div>
                    
                    <div>
                        <h4 class="font-semibold text-red-700 mb-2">Improvement Areas ({{ analysis.improvement_areas|length }})</h4>
                        <ul class="text-sm text-gray-700 space-y-1">
                            {% for area in analysis.improvement_areas[:3] %}
                            <li>• {{ area }}</li>
                            {% endfor %}
                            {% if analysis.improvement_areas|length > 3 %}
                            <li class="text-gray-500">... and {{ analysis.improvement_areas|length - 3 }} more</li>
                            {% endif %}
                        </ul>
                    </div>
                </div>
                
                <button onclick="showFullAnalysis('{{ analysis.call_id }}')" class="text-blue-500 hover:text-blue-700 text-sm font-semibold">
                    View Full Analysis
                </button>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="text-center py-12">
            <p class="text-gray-500 text-lg mb-4">No call analyses available yet.</p>
            <a href="/" class="text-blue-500 hover:text-blue-700">Go back to dashboard to analyze some calls</a>
        </div>
        {% endif %}
    </div>

    <script>
        function showFullAnalysis(callId) {
            window.location.href = `/analysis/${callId}`;
        }
    </script>
</body>
</html>
'''

DETAILED_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Call Analysis - {{ analysis.call_id }}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <div class="mb-8">
            <nav class="flex space-x-4">
                <a href="/" class="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600">Dashboard</a>
                <a href="/analyses" class="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600">Back to Analyses</a>
            </nav>
        </div>
        
        <div class="bg-white rounded-lg shadow-md p-8">
            <div class="flex justify-between items-start mb-8">
                <div>
                    <h1 class="text-3xl font-bold text-gray-800">Call Analysis Details</h1>
                    <p class="text-gray-600 mt-2">Call ID: <code class="bg-gray-100 px-2 py-1 rounded">{{ analysis.call_id }}</code></p>
                    <p class="text-gray-600">Analyzed: {{ analysis.analyzed_at[:16] if analysis.analyzed_at else "N/A" }} | Duration: {{ analysis.duration or 'N/A' }}s</p>
                </div>
                <div class="text-center bg-gray-50 rounded-lg p-4">
                    <div class="text-4xl font-bold {% if analysis.performance_score >= 8 %}text-green-600{% elif analysis.performance_score >= 6 %}text-yellow-600{% else %}text-red-600{% endif %} mb-2">
                        {{ "%.1f"|format(analysis.performance_score) }}
                    </div>
                    <div class="text-gray-600 font-semibold">out of 10</div>
                </div>
            </div>
            
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
                <div class="bg-green-50 rounded-lg p-6 border-l-4 border-green-500">
                    <h2 class="text-lg font-semibold text-green-800 mb-4">Strengths</h2>
                    <ul class="space-y-2">
                        {% for strength in analysis.strengths %}
                        <li class="flex items-start">
                            <span class="text-green-600 mr-2 mt-1">•</span>
                            <span class="text-gray-700">{{ strength }}</span>
                        </li>
                        {% endfor %}
                    </ul>
                </div>
                
                <div class="bg-red-50 rounded-lg p-6 border-l-4 border-red-500">
                    <h2 class="text-lg font-semibold text-red-800 mb-4">Areas for Improvement</h2>
                    <ul class="space-y-2">
                        {% for area in analysis.improvement_areas %}
                        <li class="flex items-start">
                            <span class="text-red-600 mr-2 mt-1">•</span>
                            <span class="text-gray-700">{{ area }}</span>
                        </li>
                        {% endfor %}
                    </ul>
                </div>
            </div>
            
            {% if analysis.prompt_suggestions %}
            <div class="bg-blue-50 rounded-lg p-6 mb-8 border-l-4 border-blue-500">
                <h2 class="text-lg font-semibold text-blue-800 mb-4">Prompt Improvement Suggestions</h2>
                <ul class="space-y-2">
                    {% for suggestion in analysis.prompt_suggestions %}
                    <li class="flex items-start">
                        <span class="text-blue-600 mr-2 mt-1">•</span>
                        <span class="text-gray-700">{{ suggestion }}</span>
                    </li>
                    {% endfor %}
                </ul>
            </div>
            {% endif %}
            
            {% if analysis.compliance_issues %}
            <div class="bg-orange-50 rounded-lg p-6 mb-8 border-l-4 border-orange-500">
                <h2 class="text-lg font-semibold text-orange-800 mb-4">Compliance Issues</h2>
                <ul class="space-y-2">
                    {% for issue in analysis.compliance_issues %}
                    <li class="flex items-start">
                        <span class="text-orange-600 mr-2 mt-1">•</span>
                        <span class="text-gray-700">{{ issue }}</span>
                    </li>
                    {% endfor %}
                </ul>
            </div>
            {% endif %}
            
            <div class="bg-gray-50 rounded-lg p-6 border-l-4 border-gray-500">
                <h2 class="text-lg font-semibold text-gray-800 mb-4">Detailed Analysis</h2>
                <div class="text-gray-700 whitespace-pre-wrap leading-relaxed">{{ analysis.detailed_analysis }}</div>
            </div>
        </div>
    </div>
</body>
</html>
'''
# Add these routes to your app.py file after the existing code

@app.route('/')
def dashboard():
    """Main dashboard"""
    try:
        # Get active prompt info
        active_prompt_name = None
        if analyzer.active_prompt_id and analyzer.active_prompt_id in analyzer.system_prompts:
            active_prompt_name = analyzer.system_prompts[analyzer.active_prompt_id]['name']
        
        # Get recent analyses
        recent_analyses = list(analyzer.call_analyses.values())[-10:]  # Last 10 analyses
        recent_analyses.reverse()  # Most recent first
        
        # Calculate stats
        analyzed_count = len(analyzer.call_analyses)
        scores = [a.get('performance_score', 0) for a in analyzer.call_analyses.values()]
        avg_score = sum(scores) / len(scores) if scores else None
        
        return render_template_string(DASHBOARD_HTML, 
            active_prompt_name=active_prompt_name,
            recent_analyses=recent_analyses,
            analyzed_count=analyzed_count,
            avg_score=avg_score
        )
    except Exception as e:
        return f"Dashboard error: {str(e)}", 500

@app.route('/prompts')
def prompts():
    """System prompts management"""
    try:
        prompts_list = list(analyzer.system_prompts.values())
        prompts_list.sort(key=lambda x: x['created_at'], reverse=True)
        return render_template_string(PROMPTS_HTML, prompts=prompts_list)
    except Exception as e:
        return f"Prompts error: {str(e)}", 500

@app.route('/analyses')
def analyses():
    """Call analyses list"""
    try:
        analyses_list = list(analyzer.call_analyses.values())
        analyses_list.sort(key=lambda x: x.get('analyzed_at', ''), reverse=True)
        
        # Calculate stats
        if analyses_list:
            scores = [a.get('performance_score', 0) for a in analyses_list]
            avg_score = sum(scores) / len(scores)
            high_scores = len([s for s in scores if s >= 8])
            low_scores = len([s for s in scores if s < 6])
        else:
            avg_score = 0
            high_scores = 0
            low_scores = 0
        
        return render_template_string(ANALYSES_HTML, 
            analyses=analyses_list,
            avg_score=avg_score,
            high_scores=high_scores,
            low_scores=low_scores
        )
    except Exception as e:
        return f"Analyses error: {str(e)}", 500

@app.route('/analysis/<call_id>')
def detailed_analysis(call_id):
    """Detailed analysis view"""
    try:
        if call_id in analyzer.call_analyses:
            analysis = analyzer.call_analyses[call_id]
            return render_template_string(DETAILED_HTML, analysis=analysis)
        else:
            return "Analysis not found", 404
    except Exception as e:
        return f"Analysis detail error: {str(e)}", 500

# API Routes
@app.route('/api/prompts', methods=['POST'])
def add_prompt():
    """Add a new system prompt"""
    try:
        data = request.get_json()
        if not data or 'name' not in data or 'prompt' not in data:
            return jsonify({"error": "Name and prompt are required"}), 400
        
        prompt_id = analyzer.add_system_prompt(data['name'], data['prompt'])
        return jsonify({"message": "Prompt added successfully", "id": prompt_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/prompts/<prompt_id>/activate', methods=['POST'])
def activate_prompt(prompt_id):
    """Activate a system prompt"""
    try:
        if prompt_id not in analyzer.system_prompts:
            return jsonify({"error": "Prompt not found"}), 404
        
        analyzer.activate_prompt(prompt_id)
        return jsonify({"message": "Prompt activated successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/prompts/<prompt_id>', methods=['DELETE'])
def delete_prompt(prompt_id):
    """Delete a system prompt"""
    try:
        if prompt_id not in analyzer.system_prompts:
            return jsonify({"error": "Prompt not found"}), 404
        
        # Don't delete if it's the active prompt
        if prompt_id == analyzer.active_prompt_id:
            return jsonify({"error": "Cannot delete active prompt"}), 400
        
        del analyzer.system_prompts[prompt_id]
        return jsonify({"message": "Prompt deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analyze-recent', methods=['POST'])
def analyze_recent_calls():
    """Manually trigger analysis of recent calls"""
    try:
        active_prompt = analyzer.get_active_prompt()
        if not active_prompt:
            return jsonify({"error": "No active system prompt found"}), 400
        
        # Run async analysis in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            analyses = loop.run_until_complete(
                analyzer.process_recent_calls(active_prompt, hours_back=24)
            )
            return jsonify({
                "message": "Analysis completed successfully",
                "analyzed_calls": len(analyses)
            })
        finally:
            loop.close()
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/analysis/<call_id>')
def get_analysis(call_id):
    """Get detailed analysis for a specific call"""
    try:
        if call_id in analyzer.call_analyses:
            return jsonify(analyzer.call_analyses[call_id])
        else:
            return jsonify({"error": "Analysis not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/vapi', methods=['POST'])
def vapi_webhook():
    """Handle VAPI webhooks"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        print(f"Received webhook: {data.get('type', 'unknown')}")
        
        if data.get('type') == 'call-ended':
            # Process in background to avoid timeout
            def process_webhook():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(webhook_handler.handle_call_ended(data))
                finally:
                    loop.close()
            
            # Start background thread
            thread = threading.Thread(target=process_webhook)
            thread.daemon = True
            thread.start()
            
            return jsonify({"message": "Webhook received, processing in background"})
        
        return jsonify({"message": "Webhook received"})
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "active_prompt": analyzer.active_prompt_id is not None,
        "analyzed_calls": len(analyzer.call_analyses),
        "system_prompts": len(analyzer.system_prompts)
    })

# Test endpoint for development
@app.route('/api/test-analysis', methods=['POST'])
def test_analysis():
    """Test endpoint to simulate call analysis"""
    try:
        # Sample transcript for testing
        sample_transcript = """
        Agent: Hello, thank you for calling our customer service. My name is Sarah, how can I help you today?
        
        Customer: Hi, I'm having trouble with my recent order. I ordered a laptop but received the wrong model.
        
        Agent: I'm sorry to hear that happened. Let me help you resolve this right away. Can you please provide me with your order number?
        
        Customer: Yes, it's ORD-12345.
        
        Agent: Thank you. I can see your order here. You ordered the Dell XPS 13 but received the Dell Inspiron 15, is that correct?
        
        Customer: Yes, exactly.
        
        Agent: I sincerely apologize for this mix-up. I can arrange for a return pickup and send you the correct laptop immediately. We'll also expedite the shipping at no extra cost. Would that work for you?
        
        Customer: That sounds great, thank you so much for your help.
        
        Agent: Perfect! I've arranged the pickup for tomorrow between 9 AM and 5 PM, and your correct laptop will be shipped today with overnight delivery. You should receive it by tomorrow evening. Is there anything else I can help you with?
        
        Customer: No, that covers everything. Thank you for resolving this so quickly.
        
        Agent: You're very welcome! Thank you for your patience, and have a great day!
        """
        
        # Get active system prompt
        active_prompt = analyzer.get_active_prompt()
        if not active_prompt:
            return jsonify({"error": "No active system prompt found"}), 400
        
        # Run analysis
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            analysis = loop.run_until_complete(
                analyzer.analyze_call_performance(
                    sample_transcript, 
                    active_prompt, 
                    "test_call_001"
                )
            )
            return jsonify({
                "message": "Test analysis completed successfully",
                "analysis": analysis
            })
        finally:
            loop.close()
            
    except Exception as e:
        return jsonify({"error": f"Test analysis failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)