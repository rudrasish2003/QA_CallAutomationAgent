import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os
from dataclasses import dataclass
import asyncio
import aiohttp
from openai import AsyncOpenAI

@dataclass
class CallAnalysis:
    call_id: str
    transcript: str
    performance_score: float
    strengths: List[str]
    improvement_areas: List[str]
    prompt_suggestions: List[str]
    compliance_issues: List[str]
    detailed_analysis: str

class VAPIAnalyzer:
    def __init__(self, vapi_api_key: str, openai_api_key: str):
        self.vapi_api_key = vapi_api_key
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)
        self.vapi_base_url = "https://api.vapi.ai"
        
        # In-memory storage for system prompts and analyses
        self.system_prompts = {}
        self.active_prompt_id = None
        self.call_analyses = {}  # call_id -> analysis
        
    def add_system_prompt(self, name: str, prompt: str) -> str:
        """Add a new system prompt and return its ID"""
        prompt_id = f"prompt_{len(self.system_prompts) + 1}"
        self.system_prompts[prompt_id] = {
            'id': prompt_id,
            'name': name,
            'prompt': prompt,
            'created_at': datetime.now().isoformat(),
            'is_active': False
        }
        return prompt_id
    
    def activate_prompt(self, prompt_id: str):
        """Activate a system prompt"""
        # Deactivate all prompts
        for pid in self.system_prompts:
            self.system_prompts[pid]['is_active'] = False
        
        # Activate the selected prompt
        if prompt_id in self.system_prompts:
            self.system_prompts[prompt_id]['is_active'] = True
            self.active_prompt_id = prompt_id
    
    def get_active_prompt(self) -> Optional[str]:
        """Get the active system prompt"""
        if self.active_prompt_id and self.active_prompt_id in self.system_prompts:
            return self.system_prompts[self.active_prompt_id]['prompt']
        return None
    
    def get_call_logs(self, limit: int = 50, status: str = "ended") -> List[Dict]:
        """Fetch call logs from VAPI"""
        headers = {
            "Authorization": f"Bearer {self.vapi_api_key}",
            "Content-Type": "application/json"
        }
        
        params = {
            "limit": limit,
            "status": status
        }
        
        try:
            response = requests.get(
                f"{self.vapi_base_url}/call",
                headers=headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                # Handle both array response and object with data property
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'data' in data:
                    return data['data']
                else:
                    print(f"Unexpected response format: {type(data)}")
                    return []
            else:
                print(f"Failed to fetch calls: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"Error fetching call logs: {str(e)}")
            return []
    
    def get_call_transcript(self, call_id: str) -> str:
        """Fetch transcript for a specific call"""
        headers = {
            "Authorization": f"Bearer {self.vapi_api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(
                f"{self.vapi_base_url}/call/{call_id}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                call_data = response.json()
                
                # Try different ways to extract transcript
                if 'transcript' in call_data and call_data['transcript']:
                    return call_data['transcript']
                
                if 'messages' in call_data:
                    messages = call_data['messages']
                    transcript_parts = []
                    for msg in messages:
                        role = msg.get('role', 'unknown')
                        content = msg.get('content', '')
                        if content:
                            transcript_parts.append(f"{role.title()}: {content}")
                    return "\n".join(transcript_parts)
                
                # Check for artifact or other transcript formats
                if 'artifact' in call_data and 'transcript' in call_data['artifact']:
                    return call_data['artifact']['transcript']
                
                # Check for recordingUrl and attempt to get transcript
                if 'recordingUrl' in call_data:
                    print(f"Call {call_id} has recording but no transcript available yet")
                    return "Transcript not yet available - recording found"
                
                return "No transcript available"
            else:
                print(f"Failed to fetch transcript for {call_id}: {response.status_code} - {response.text}")
                return ""
        except Exception as e:
            print(f"Error fetching transcript for call {call_id}: {str(e)}")
            return ""
    
    async def analyze_call_performance(self, transcript: str, system_prompt: str, call_id: str = None) -> Dict:
        """Analyze call performance using OpenAI"""
        
        analysis_prompt = f"""
You are an expert call quality analyst. Please analyze this customer service call transcript based on the given system prompt/guidelines.

SYSTEM PROMPT/GUIDELINES:
{system_prompt}

CALL TRANSCRIPT:
{transcript}

Please provide a detailed analysis in the following JSON format ONLY (no additional text):
{{
    "performance_score": <float between 0-10>,
    "strengths": ["strength1", "strength2", "strength3"],
    "improvement_areas": ["area1", "area2", "area3"],
    "prompt_suggestions": ["suggestion1", "suggestion2"],
    "compliance_issues": ["issue1", "issue2"],
    "detailed_analysis": "Comprehensive 2-3 paragraph analysis of the call performance, highlighting key observations and recommendations"
}}

Evaluation Criteria:
1. Adherence to system prompt guidelines (30%)
2. Customer satisfaction and experience (25%)
3. Problem resolution effectiveness (20%)
4. Communication clarity and professionalism (15%)
5. Compliance with procedures (10%)

Provide specific, actionable feedback. If no issues found in a category, use empty array.
"""

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",  # Updated to current model
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a professional call quality analyst. Respond only with valid JSON as requested."
                    },
                    {
                        "role": "user",
                        "content": analysis_prompt
                    }
                ],
                max_tokens=2000,
                temperature=0.3
            )
            
            analysis_text = response.choices[0].message.content.strip()
            
            # Try to parse JSON from response
            try:
                # Remove any markdown code blocks if present
                if '```json' in analysis_text:
                    analysis_text = analysis_text.split('```json')[1].split('```')[0]
                elif '```' in analysis_text:
                    analysis_text = analysis_text.split('```')[1]
                
                analysis_json = json.loads(analysis_text.strip())
                
                # Validate required fields
                required_fields = ['performance_score', 'strengths', 'improvement_areas', 'prompt_suggestions', 'compliance_issues', 'detailed_analysis']
                for field in required_fields:
                    if field not in analysis_json:
                        analysis_json[field] = [] if field != 'performance_score' and field != 'detailed_analysis' else (5.0 if field == 'performance_score' else "Analysis completed")
                
                # Ensure performance_score is a float
                analysis_json['performance_score'] = float(analysis_json['performance_score'])
                
                # Store in memory
                if call_id:
                    self.call_analyses[call_id] = {
                        **analysis_json,
                        'call_id': call_id,
                        'analyzed_at': datetime.now().isoformat(),
                        'transcript': transcript[:1000] + "..." if len(transcript) > 1000 else transcript  # Truncate long transcripts for storage
                    }
                
                return analysis_json
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing error: {e}")
                print(f"Raw response: {analysis_text}")
                # Return fallback analysis
                return {
                    "performance_score": 5.0,
                    "strengths": ["Call completed successfully"],
                    "improvement_areas": ["Manual review recommended - analysis parsing failed"],
                    "prompt_suggestions": ["System prompt may need refinement"],
                    "compliance_issues": [],
                    "detailed_analysis": f"Automated analysis encountered parsing issues. Raw AI response: {analysis_text[:500]}..."
                }
                
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return {
                "performance_score": 0.0,
                "strengths": [],
                "improvement_areas": ["Analysis failed - API error"],
                "prompt_suggestions": [],
                "compliance_issues": ["System error during analysis"],
                "detailed_analysis": f"Analysis failed due to API error: {str(e)}"
            }
    
    async def process_recent_calls(self, system_prompt: str, hours_back: int = 24) -> List[Dict]:
        """Process recent calls and analyze them"""
        print(f"Fetching calls from last {hours_back} hours...")
        calls = self.get_call_logs(limit=100)  # Increased limit to get more calls
        
        if not calls:
            print("No calls found")
            return []
        
        print(f"Retrieved {len(calls)} total calls from VAPI")
        
        # Filter calls from the last X hours
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        recent_calls = []
        
        for call in calls:
            try:
                # Handle different timestamp formats
                created_at = call.get('createdAt', call.get('created_at', ''))
                if created_at:
                    # Parse ISO datetime with timezone info
                    try:
                        if created_at.endswith('Z'):
                            call_time = datetime.fromisoformat(created_at[:-1] + '+00:00')
                        else:
                            call_time = datetime.fromisoformat(created_at)
                        
                        # Convert to UTC if timezone aware
                        if call_time.tzinfo is not None:
                            call_time = call_time.replace(tzinfo=None)
                        
                        if call_time > cutoff_time:
                            recent_calls.append(call)
                    except ValueError as ve:
                        print(f"Date parsing error for {created_at}: {ve}")
                        # Include call anyway if we can't parse the time
                        recent_calls.append(call)
            except Exception as e:
                print(f"Error parsing call time: {e}")
                # Include call anyway if we can't parse the time
                recent_calls.append(call)
        
        print(f"Found {len(recent_calls)} recent calls to analyze")
        
        # Analyze each call (limit to avoid API rate limits and costs)
        analyses = []
        max_calls_to_analyze = min(10, len(recent_calls))  # Analyze up to 10 calls
        
        for i, call in enumerate(recent_calls[:max_calls_to_analyze]):
            try:
                call_id = call['id']
                print(f"Processing call {i+1}/{max_calls_to_analyze}: {call_id}")
                
                # Skip if already analyzed
                if call_id in self.call_analyses:
                    print(f"Call {call_id} already analyzed, skipping")
                    analyses.append(self.call_analyses[call_id])
                    continue
                
                transcript = self.get_call_transcript(call_id)
                
                if transcript.strip() and transcript != "No transcript available" and transcript != "Transcript not yet available - recording found":
                    analysis = await self.analyze_call_performance(transcript, system_prompt, call_id)
                    analysis['call_id'] = call_id
                    analysis['call_time'] = call.get('createdAt', call.get('created_at'))
                    analysis['duration'] = call.get('duration', call.get('endedAt', 0))
                    analyses.append(analysis)
                    print(f"Successfully analyzed call {call_id} - Score: {analysis.get('performance_score', 'N/A')}")
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(1)
                else:
                    print(f"No transcript available for call {call_id}: {transcript}")
            except Exception as e:
                print(f"Error processing call {call.get('id', 'unknown')}: {str(e)}")
                continue
        
        print(f"Successfully analyzed {len(analyses)} calls")
        return analyses
    
    def generate_summary_report(self, analyses: List[Dict]) -> Dict:
        """Generate a summary report from multiple call analyses"""
        if not analyses:
            return {"error": "No analyses to summarize"}
        
        total_calls = len(analyses)
        scores = [a.get('performance_score', 0) for a in analyses]
        avg_score = sum(scores) / total_calls if scores else 0
        
        # Aggregate common issues and strengths
        all_strengths = []
        all_improvements = []
        all_prompt_suggestions = []
        all_compliance_issues = []
        
        for analysis in analyses:
            all_strengths.extend(analysis.get('strengths', []))
            all_improvements.extend(analysis.get('improvement_areas', []))
            all_prompt_suggestions.extend(analysis.get('prompt_suggestions', []))
            all_compliance_issues.extend(analysis.get('compliance_issues', []))
        
        # Count frequency of issues/strengths
        def count_items(items):
            counts = {}
            for item in items:
                counts[item] = counts.get(item, 0) + 1
            return sorted(counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "summary": {
                "total_calls_analyzed": total_calls,
                "average_performance_score": round(avg_score, 2),
                "score_range": {
                    "highest": max(scores) if scores else 0,
                    "lowest": min(scores) if scores else 0
                },
                "score_distribution": {
                    "excellent (8-10)": len([s for s in scores if s >= 8]),
                    "good (6-8)": len([s for s in scores if 6 <= s < 8]),
                    "needs_improvement (0-6)": len([s for s in scores if s < 6])
                }
            },
            "top_strengths": count_items(all_strengths)[:5],
            "top_improvement_areas": count_items(all_improvements)[:5],
            "prompt_optimization_suggestions": list(set(all_prompt_suggestions)),
            "compliance_concerns": list(set(all_compliance_issues)),
            "individual_analyses": analyses
        }

# Example webhook handler
class VAPIWebhookHandler:
    def __init__(self, analyzer: VAPIAnalyzer):
        self.analyzer = analyzer
    
    async def handle_call_ended(self, call_data: Dict):
        """Handle webhook when call ends"""
        call_id = call_data.get('id')
        system_prompt = self.analyzer.get_active_prompt()
        
        if not system_prompt:
            print("No active system prompt found")
            return None
        
        try:
            print(f"Processing call {call_id}")
            
            # Wait a bit for transcript to be processed by VAPI
            print("Waiting for transcript to be processed...")
            await asyncio.sleep(10)  # Increased wait time
            
            transcript = self.analyzer.get_call_transcript(call_id)
            if transcript and transcript != "No transcript available" and transcript != "Transcript not yet available - recording found":
                analysis = await self.analyzer.analyze_call_performance(transcript, system_prompt, call_id)
                print(f"Successfully analyzed call {call_id} - Score: {analysis.get('performance_score', 'N/A')}")
                return analysis
            else:
                print(f"No transcript available for call {call_id}: {transcript}")
                return None
                
        except Exception as e:
            print(f"Error analyzing call {call_id}: {str(e)}")
            return None

# Usage example
async def main():
    # Initialize the analyzer
    vapi_key = os.getenv("VAPI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not vapi_key or not openai_key:
        print("Please set VAPI_API_KEY and OPENAI_API_KEY environment variables")
        return
    
    analyzer = VAPIAnalyzer(
        vapi_api_key=vapi_key,
        openai_api_key=openai_key
    )
    
    # Add a default system prompt
    prompt_id = analyzer.add_system_prompt(
        "Customer Service Standard",
        """
        You are a customer service agent. Your goals are to:
        1. Greet customers warmly and professionally
        2. Listen actively to understand their needs
        3. Provide accurate and helpful information
        4. Resolve issues efficiently and completely
        5. Maintain a positive and empathetic tone throughout
        6. Follow company policies and procedures
        7. End calls with confirmation and next steps
        8. Ensure customer satisfaction before ending the call
        
        Key Performance Indicators:
        - First call resolution rate
        - Customer satisfaction
        - Professional communication
        - Compliance with policies
        - Problem-solving effectiveness
        """
    )
    analyzer.activate_prompt(prompt_id)
    
    # Process recent calls
    active_prompt = analyzer.get_active_prompt()
    if active_prompt:
        print("Analyzing recent calls...")
        analyses = await analyzer.process_recent_calls(active_prompt, hours_back=24)
        
        if analyses:
            # Generate summary report
            report = analyzer.generate_summary_report(analyses)
            print("\n" + "="*50)
            print("SUMMARY REPORT")
            print("="*50)
            print(json.dumps(report, indent=2))
        else:
            print("No recent calls found to analyze")
    else:
        print("No active system prompt found")

if __name__ == "__main__":
    asyncio.run(main())