import os
import json
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langchain_litellm import ChatLiteLLM  # Updated import from langchain-litellm package
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter  # Optional, for plain text formatting
import markdown
import re  # For URL parsing

# Set the API key - LiteLLM expects NVIDIA_NIM_API_KEY for nvidia_nim models
os.environ["NVIDIA_NIM_API_KEY"] = "     "

# Initialize the LLM using ChatLiteLLM from langchain-litellm package
llm = ChatLiteLLM(
    model="nvidia_nim/nvidia/llama-3.1-nemotron-nano-8b-v1",
    temperature=0.1,  # Low temperature for consistent, precise outputs
    api_key=os.environ["NVIDIA_NIM_API_KEY"]
)

# Define the state
class State(TypedDict):
    youtube_url: str
    transcript: str
    markdown_notes: str
    image_prompt: str
    detailed_notes: str
    needs_review: bool

# Node: Extract transcript from YouTube URL (Updated to use modern API)
def get_transcript(state: State) -> State:
    print("\n[1/5] Fetching YouTube transcript...")
    url = state["youtube_url"]
    # Extract video ID from URL (assumes standard YouTube watch?v= format)
    video_id_match = re.search(r"(?<=v=)[^&]+", url)
    if not video_id_match:
        raise ValueError("Invalid YouTube URL: Could not extract video ID.")
    video_id = video_id_match.group(0)
    
    try:
        # Use the recommended modern approach: create instance and fetch
        ytt_api = YouTubeTranscriptApi()
        fetched_transcript = ytt_api.fetch(video_id, languages=['en'])
        # Join the text from snippets into a single string
        transcript = " ".join([snippet.text for snippet in fetched_transcript.snippets])
        print(f"   ✓ Transcript fetched ({len(transcript)} characters)")
    except Exception as e:
        # Fallback or error handling (e.g., if no English transcript available)
        raise ValueError(f"Failed to fetch transcript: {str(e)}. Ensure the video has captions enabled.")
    
    return {"transcript": transcript}

# Node: Create Markdown notes with mermaid diagram and table
def create_markdown_notes(state: State) -> State:
    print("\n[2/5] Creating markdown notes with AI...")
    prompt = f"""
    Create comprehensive Markdown notes based on the following YouTube video transcript. 
    Structure the notes clearly, and include:
    - A summary section.
    - A Mermaid diagram representing the key workflow or concepts (use 'graph TD' or appropriate Mermaid syntax).
    - A table summarizing main points (use Markdown table format with columns like 'Topic', 'Key Insight', 'Details').
    
    Transcript:
    {state["transcript"]}
    
    Output only the Markdown content.
    """
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    notes = response.content.strip()
    print(f"   ✓ Markdown notes created")
    
    return {"markdown_notes": notes}

# Node: Create image prompt
def create_image_prompt(state: State) -> State:
    print("\n[3/5] Generating image prompt...")
    prompt = f"""
    Based on the YouTube video transcript, generate a detailed prompt for creating a single illustrative image that captures the essence of the video's main theme or a key visual concept. 
    The prompt should be suitable for an AI image generator (e.g., detailed, vivid description including style, composition, and elements).
    
    Transcript:
    {state["transcript"]}
    
    Output only the image prompt.
    """
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    img_prompt = response.content.strip()
    print(f"   ✓ Image prompt generated")
    
    return {"image_prompt": img_prompt}

# Node: Create detailed notes incorporating Markdown notes, image prompt, mermaid, and table
def create_detailed_notes(state: State) -> State:
    print("\n[4/5] Creating detailed notes...")
    # Placeholder for image: Since actual image generation is not implemented here, embed the prompt as alt text in a Markdown image syntax (user can replace with generated image URL/path later).
    image_placeholder = f"![Illustrative image based on video: {state['image_prompt']}](generated_image.png)"
    
    prompt = f"""
    Create detailed Markdown notes by expanding on the provided Markdown notes. 
    Incorporate:
    - The image placeholder where visually relevant.
    - Ensure the Mermaid diagram and table from the Markdown notes are preserved and integrated seamlessly.
    - Add any additional details for clarity.
    
    Markdown notes:
    {state["markdown_notes"]}
    
    Image placeholder to include: {image_placeholder}
    
    Output only the updated Markdown content.
    """
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    detailed = response.content.strip()
    print(f"   ✓ Detailed notes created")
    
    return {"detailed_notes": detailed}

# Node: Check if review is needed (text correctness and image prompt quality)
def should_review(state: State) -> State:
    prompt = f"""
    Review the detailed notes and image prompt for quality:
    - Is the text in the detailed notes accurate, coherent, and free of errors based on the context?
    - Is the image prompt detailed enough to generate a high-quality, relevant image (e.g., vivid, specific, no ambiguities)?
    
    Detailed notes:
    {state["detailed_notes"][:2000]}  # Truncate for prompt length
    
    Image prompt:
    {state["image_prompt"]}
    
    Respond with valid JSON: {{"needs_review": true or false, "reason": "Brief explanation"}}
    """
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    try:
        data = json.loads(response.content.strip())
        needs_review = data.get("needs_review", False)
    except json.JSONDecodeError:
        # Fallback if JSON invalid
        needs_review = True
    
    return {"needs_review": needs_review}

# Node: Review and correct (invoked if review needed)
def review_agent(state: State) -> State:
    prompt = f"""
    Act as a review agent. Correct any inaccuracies in the text of the detailed notes. 
    Also, refine the image prompt if it would not generate a good image (make it more detailed and effective).
    Provide the fully updated detailed notes in Markdown, incorporating corrections.
    
    Detailed notes to review:
    {state["detailed_notes"]}
    
    Current image prompt: {state["image_prompt"]}
    
    Output only the corrected Markdown detailed notes. Update the image placeholder if the prompt changes.
    """
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    corrected_notes = response.content.strip()
    
    # Update image prompt if needed (simple re-invocation for refinement)
    refine_prompt = f"Refine this image prompt for better image generation quality: {state['image_prompt']}. Output only the refined prompt."
    img_response = llm.invoke([HumanMessage(content=refine_prompt)])
    refined_img_prompt = img_response.content.strip()
    
    # Re-embed placeholder with refined prompt if necessary (simple string replacement)
    if state["image_prompt"] != refined_img_prompt:
        corrected_notes = corrected_notes.replace(state["image_prompt"], refined_img_prompt)
    
    return {
        "detailed_notes": corrected_notes,
        "image_prompt": refined_img_prompt,
        "needs_review": False  # Assume corrected
    }

# Node: Save to MD and HTML files (Filesystem MCP equivalent)
def save_files(state: State) -> State:
    print("\n[5/5] Saving files...")
    detailed_notes = state["detailed_notes"]
    
    # Save Markdown
    with open("notes.md", "w", encoding="utf-8") as f:
        f.write(detailed_notes)
    
    # Convert to HTML (basic; Mermaid requires additional JS for rendering, e.g., via Mermaid CDN)
    html_content = markdown.markdown(detailed_notes, extensions=['tables', 'fenced_code'])
    html_full = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>YouTube Notes</title>
        <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
        <script>mermaid.initialize({{startOnLoad: true}});</script>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """
    
    with open("notes.html", "w", encoding="utf-8") as f:
        f.write(html_full)
    
    print("   ✓ Files saved: notes.md and notes.html")
    return state

# Build the graph
workflow = StateGraph(State)

# Add nodes
workflow.add_node("get_transcript", get_transcript)
workflow.add_node("create_markdown_notes", create_markdown_notes)
workflow.add_node("create_image_prompt", create_image_prompt)
workflow.add_node("create_detailed_notes", create_detailed_notes)
workflow.add_node("should_review", should_review)
workflow.add_node("review_agent", review_agent)
workflow.add_node("save_files", save_files)

# Add edges
workflow.set_entry_point("get_transcript")
workflow.add_edge("get_transcript", "create_markdown_notes")
workflow.add_edge("create_markdown_notes", "create_image_prompt")
workflow.add_edge("create_image_prompt", "create_detailed_notes")

# Conditional edge after detailed notes: Note - should_review is a node that sets needs_review
# We need to route based on the state after should_review
def route_after_detailed(state: State):
    # Run should_review to update state
    updated_state = should_review(state)
    return "review_agent" if updated_state["needs_review"] else "save_files"

workflow.add_edge("create_detailed_notes", "should_review")
workflow.add_conditional_edges(
    "should_review",
    lambda s: "review_agent" if s["needs_review"] else "save_files"
)
workflow.add_edge("review_agent", "save_files")
workflow.add_edge("save_files", END)

# Compile the graph
app = workflow.compile()

# Example usage
if __name__ == "__main__":
    initial_state = {
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Replace with actual URL (example: Rick Astley video for testing)
        "transcript": "",
        "markdown_notes": "",
        "image_prompt": "",
        "detailed_notes": "",
        "needs_review": False
    }
    print("Starting workflow...")
    print(f"Processing video: {initial_state['youtube_url']}")
    result = app.invoke(initial_state)
    print("\n" + "="*50)
    print("Workflow completed successfully!")
    print("Generated files: notes.md and notes.html")
    print("="*50)