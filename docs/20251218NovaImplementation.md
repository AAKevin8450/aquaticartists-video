# AWS Nova Integration Plan
*Date: 2025-12-18*
*Status: Research & Planning Phase*

## Executive Summary

Amazon Nova represents AWS's new generation of foundation models available through Amazon Bedrock, offering frontier multimodal AI capabilities that can understand and analyze video, image, and text content simultaneously. Nova models provide intelligent video comprehension that goes beyond traditional computer vision services like Amazon Rekognition, delivering contextual understanding, natural language summaries, semantic chapter detection, and element identification based on both visual and audio content.

Integrating Nova into our video analysis application will provide users with AI-powered narrative understanding and intelligent insights that complement Rekognition's technical detection capabilities. While Rekognition excels at frame-by-frame object detection, facial analysis, and technical segment identification, Nova offers semantic comprehension—understanding what the video is about, identifying logical chapters based on content transitions, summarizing key themes, and correlating visual elements with audio discussions. This complementary approach gives users the choice between technical analysis (Rekognition), intelligent comprehension (Nova), or both simultaneously for comprehensive video understanding.

The implementation will support all Nova understanding models (Micro, Lite, Pro, and Premier) with intelligent model selection based on video duration and user quality preferences. For long-form content exceeding context windows, we'll implement an automatic chunking strategy that splits videos into overlapping segments, processes them independently, and aggregates results using advanced prompt engineering to maintain narrative coherence. The system will handle videos from 30 seconds to multiple hours, providing video summaries, automatic chapter detection with descriptive titles, equipment and object identification, speaker diarization, and topic extraction—all integrated into the existing Flask application with new database schemas, API endpoints, UI components, and export functionality.

## 1. AWS Nova Service Overview

### 1.1 What is AWS Nova?

Amazon Nova is AWS's family of foundation models available through Amazon Bedrock, announced in December 2024. Nova models are designed to provide frontier intelligence with industry-leading price performance, offering multimodal capabilities that can process and understand text, images, and video content within a single unified model. Unlike specialized services like Amazon Rekognition that focus on computer vision tasks, Nova models provide holistic content understanding by analyzing visual, audio, and textual information together.

Nova is positioned as Amazon's answer to other multimodal foundation models like GPT-4 Vision and Google's Gemini, offering competitive performance at lower costs. The models are optimized for enterprise use cases including content analysis, video summarization, document understanding, and multimodal embeddings for RAG (Retrieval-Augmented Generation) applications.

Key differentiators:
- **Multimodal understanding**: Process video + audio + text in single request
- **Long context support**: Up to 300K tokens (Lite/Pro) or 1M tokens (Premier)
- **Flexible deployment**: Available through Amazon Bedrock's unified API
- **Cost optimization**: Tiered models allow balance between cost and capability
- **Regional availability**: Accessible in multiple AWS regions through Bedrock

### 1.2 Model Comparison

| Feature | Nova Micro | Nova Lite | Nova Pro | Nova Premier |
|---------|------------|-----------|----------|--------------|
| **Context Window** | 128K tokens | 300K tokens | 300K tokens | 1M tokens (2M+ in early 2025) |
| **Video Duration** | ~12 minutes | ~30 minutes | ~30 minutes | ~90 minutes |
| **Max Video Size** | 1 GB (via S3) | 1 GB (via S3) | 1 GB (via S3) | 1 GB (via S3) |
| **Frame Sampling** | 1 FPS (≤16 min) | 1 FPS (≤16 min) | 1 FPS (≤16 min) | 1 FPS (up to 3200 frames) |
| **Processing Speed** | Fastest | Fast | Moderate | Slower (higher quality) |
| **Input Price** | $0.035/1K tokens | $0.06/1K tokens | $0.80/1K tokens | Premium pricing |
| **Output Price** | $0.14/1K tokens | $0.24/1K tokens | $3.20/1K tokens | Premium pricing |
| **Best Use Case** | Quick summaries, batch processing | Balanced analysis | Detailed comprehension | Enterprise critical analysis |
| **Recommended For** | Cost-sensitive, high-volume | General video understanding | Complex reasoning required | Maximum accuracy needed |

**Trade-offs Analysis**:

- **Nova Micro**: Best for applications requiring rapid processing of many short videos where cost is primary concern. Suitable for preview generation, basic categorization, or first-pass filtering. The 128K context window limits video duration to approximately 12 minutes.

- **Nova Lite**: The recommended default for most use cases. Offers 300K context window (30-minute videos), good quality comprehension, and competitive pricing. Strikes optimal balance for tutorial videos, presentations, webinars, and product reviews.

- **Nova Pro**: Designed for scenarios requiring sophisticated reasoning, detailed analysis, or handling complex multi-speaker conversations. Higher cost justified when accuracy and depth matter more than speed. Ideal for legal depositions, medical consultations, or academic content.

- **Nova Premier**: Enterprise-grade model with 1M token context (90-minute videos), superior accuracy, and advanced reasoning. Best for mission-critical applications, compliance analysis, or when processing very long-form content like full conference sessions or feature-length documentaries.

### 1.3 Video Processing Capabilities

**Supported Formats**: MP4, MOV, MKV, AVI, FLV, MPEG, WebM, WMV, 3GP (all common video containers supported via S3 upload)

**Maximum Video Length**:
- Micro: Up to 12 minutes (128K token limit)
- Lite/Pro: Up to 30 minutes (300K token limit)
- Premier: Up to 90 minutes (1M token limit)
- **Recommendation**: Keep videos <1 hour for low motion, <16 minutes for high motion content

**Input Methods**:
- S3 URI reference (recommended for videos >10MB, required for videos >1GB)
- Base64-encoded bytes (for smaller videos, payload size limit applies)
- Direct file upload through Bedrock API

**Audio Processing**:
- Full audio transcription and understanding
- Multi-language support (100+ languages)
- Speaker diarization (identify different speakers)
- Audio-visual correlation (match what's said with what's shown)

**Frame Analysis**:
- 1 FPS sampling rate for videos ≤16 minutes
- Adaptive sampling for longer videos (maintains 960 frames total)
- Premier model: Up to 3,200 frames processed

**What Nova CAN do**:
- Generate comprehensive video summaries with key themes and takeaways
- Detect logical chapters/segments with descriptive titles and timestamps
- Identify objects, equipment, and tools visible in frames
- Correlate visual content with audio (understand what's being discussed)
- Perform speaker diarization without facial recognition
- Extract topics, themes, and key discussion points
- Answer specific questions about video content
- Provide timestamps for events in MM:SS or SMPTE timecode format
- Process multiple languages with automatic detection
- Understand context and narrative flow across entire video
- Generate structured JSON outputs for programmatic processing

**What Nova CANNOT do**:
- Real-time video analysis (async processing only)
- Facial identification/recognition (privacy-focused, person counting only)
- Generate new video content (separate Nova Reel model for that)
- Process live streaming video (requires complete uploaded file)
- Guarantee frame-perfect timestamp accuracy (1 FPS sampling means ±1 second precision)
- Handle videos requiring specialized domain expertise without fine-tuning
- Process videos longer than context window without chunking
- Provide bounding boxes or pixel-level segmentation (use Rekognition for that)

### 1.4 API Structure & SDK Usage

**Service**: Amazon Bedrock
**API**: bedrock-runtime
**Python SDK**: boto3 >= 1.28.57

**Basic API Call Structure**:
```python
import boto3
import json
import base64

# Initialize Bedrock Runtime client
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

# Option 1: Using S3 URI (recommended for larger videos)
video_source = {
    "s3Location": {
        "uri": "s3://video-analysis-app-676206912644/videos/example.mp4"
    }
}

# Option 2: Using base64-encoded bytes (smaller videos only)
with open('video.mp4', 'rb') as f:
    video_bytes = base64.b64encode(f.read()).decode('utf-8')
    video_source = {"bytes": video_bytes}

# Prepare request using Converse API
request_body = {
    "modelId": "us.amazon.nova-lite-v1:0",  # or nova-micro, nova-pro, nova-premier
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "video": {
                        "format": "mp4",
                        "source": video_source
                    }
                },
                {
                    "text": "Provide a comprehensive summary of this video including main topics, key points, and important takeaways."
                }
            ]
        }
    ],
    "inferenceConfig": {
        "maxTokens": 4096,
        "temperature": 0.7,
        "topP": 0.9
    }
}

# Invoke model
response = bedrock.converse(
    **request_body
)

# Parse response
output_message = response['output']['message']
summary_text = output_message['content'][0]['text']

# Access usage metrics
usage = response['usage']
input_tokens = usage['inputTokens']
output_tokens = usage['outputTokens']
total_tokens = usage['totalTokens']

print(f"Summary: {summary_text}")
print(f"Tokens used: {total_tokens} (input: {input_tokens}, output: {output_tokens})")
```

**Key Request Parameters**:
- `modelId`: Specific Nova model ARN or ID (e.g., "us.amazon.nova-lite-v1:0")
- `messages`: Array of message objects with role and content
- `content`: Can include multiple modalities (video, image, text) in same request
- `inferenceConfig`: Controls output generation (max tokens, temperature, top-p)
- `temperature`: 0.0-1.0, controls randomness (use 0.1-0.3 for factual summaries)
- `maxTokens`: Maximum output length (1024-4096 typical for summaries)

**Response Structure**:
```json
{
  "output": {
    "message": {
      "role": "assistant",
      "content": [
        {
          "text": "Generated summary or analysis text..."
        }
      ]
    }
  },
  "usage": {
    "inputTokens": 15234,
    "outputTokens": 512,
    "totalTokens": 15746
  },
  "stopReason": "end_turn",
  "metrics": {
    "latencyMs": 3456
  }
}
```

### 1.5 Regional Availability

**Available Regions** (as of December 2024):
- us-east-1 (US East - N. Virginia) ✓
- us-west-2 (US West - Oregon)
- eu-west-1 (Europe - Ireland)
- ap-southeast-1 (Asia Pacific - Singapore)
- Additional regions being added regularly

**us-east-1 Support**: **YES** - Full support for all Nova models including video understanding capabilities. This is the primary launch region with complete feature availability.

**Considerations**:
- Model availability may vary by region (check Bedrock console)
- Pricing may differ slightly between regions
- Data residency requirements may dictate region selection
- For production, consider using same region as S3 bucket to minimize latency and data transfer costs
- Cross-region S3 access supported but incurs additional charges

### 1.6 IAM Permissions Required

**Required Actions**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockNovaModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-micro-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-lite-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-pro-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-premier-v1:0"
      ]
    },
    {
      "Sid": "BedrockModelDiscovery",
      "Effect": "Allow",
      "Action": [
        "bedrock:GetFoundationModel",
        "bedrock:ListFoundationModels"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3VideoAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::video-analysis-app-676206912644",
        "arn:aws:s3:::video-analysis-app-676206912644/*"
      ]
    }
  ]
}
```

**Permission Explanations**:

- `bedrock:InvokeModel`: Core permission required to call Nova models for video analysis. Without this, API calls will fail with AccessDeniedException.

- `bedrock:InvokeModelWithResponseStream`: Enables streaming responses for long outputs. While not strictly required for video analysis (which typically uses standard invoke), included for future flexibility.

- `bedrock:GetFoundationModel`: Allows application to retrieve model metadata, pricing information, and capability details. Useful for dynamic model selection and user-facing model information.

- `bedrock:ListFoundationModels`: Enables listing available models in the region. Helpful for displaying model options to users or programmatic model discovery.

- `s3:GetObject`: Required to read video files from S3 bucket for processing. Nova accesses videos via S3 URIs, so this permission allows Bedrock to retrieve the video content.

- `s3:PutObject`: Needed if storing intermediate results or processed outputs back to S3. Also required for chunking workflow where video segments are temporarily stored.

- `s3:ListBucket`: Allows listing objects in bucket, useful for batch processing scenarios or directory scanning.

**Security Best Practices**:
- Use least privilege: Grant only permissions needed
- Scope Resource ARNs to specific models and S3 paths
- Use separate IAM roles for dev/staging/production
- Enable AWS CloudTrail logging for Bedrock API calls
- Implement cost controls with AWS Budgets alerts
- Consider VPC endpoints for private connectivity to Bedrock

## 2. Feature Design Specifications

### 2.1 Video Summarization

**User Options**:
- **Summary depth**:
  - Brief (2-3 sentences, ~50 words)
  - Standard (1-2 paragraphs, ~150 words) - **Default**
  - Detailed (3-5 paragraphs, ~400 words)
- **Language**: Auto-detect (default) or specify (en, es, fr, de, ja, zh, etc.)
- **Focus areas**:
  - Overview (general summary)
  - Key points (bullet-point highlights)
  - Action items (tasks/takeaways)
  - Topics discussed (thematic analysis)

**Prompt Templates**:

*Brief Summary*:
```
Analyze this video and provide a concise 2-3 sentence summary of the main content and purpose.
Focus on what the video is about and its primary objective. Keep it under 50 words.
```

*Standard Summary* (Default):
```
Analyze this video and provide a comprehensive summary including:
1. Main topic and purpose of the video
2. Key points and important information discussed
3. Notable takeaways or conclusions

Provide the summary in 1-2 well-structured paragraphs (approximately 150 words).
Be specific and informative while remaining concise.
```

*Detailed Summary*:
```
Analyze this video thoroughly and provide a detailed summary including:

1. **Overview**: Context and purpose of the video, intended audience, and overall structure
2. **Main Topics**: Primary themes and subjects covered throughout
3. **Key Points**: Important details, facts, demonstrations, or arguments presented
4. **Notable Events**: Significant moments, transitions, or highlights
5. **Conclusions**: Takeaways, recommendations, or closing thoughts

Provide 3-5 comprehensive paragraphs with rich detail (approximately 400 words).
Include specific examples and timestamps where relevant.
```

*Key Points Extraction*:
```
Watch this video and extract the key points as a bulleted list.
For each point:
- Provide a clear, concise statement
- Include the approximate timestamp (MM:SS) when it's discussed
- Note its importance (high/medium/low priority)

Return in JSON format:
{
  "key_points": [
    {"point": "...", "timestamp": "02:15", "priority": "high"},
    ...
  ]
}
```

**Expected Output Schema**:
```json
{
  "summary": {
    "depth": "standard",
    "language": "en",
    "text": "This video provides a comprehensive tutorial on portrait photography techniques. The instructor demonstrates various camera settings including aperture selection (f/1.8-f/2.8 for bokeh), lighting setups with both natural and artificial sources, and composition strategies following the rule of thirds. Key topics include depth of field control, three-point lighting, posing techniques for subjects, and post-processing workflows in Lightroom. The tutorial includes practical demonstrations with a live model showing real-world application of the concepts discussed.",
    "word_count": 78,
    "key_topics": [
      "portrait photography",
      "camera settings",
      "lighting techniques",
      "composition",
      "post-processing"
    ],
    "generated_at": "2025-12-18T10:30:00Z",
    "model_used": "us.amazon.nova-lite-v1:0",
    "tokens_used": 15234
  }
}
```

**Use Cases**:
- **Content cataloging**: Generate descriptions for video libraries
- **Quick preview**: Understand video content before watching
- **Search optimization**: Create metadata for semantic search
- **Content moderation**: Screen videos for appropriateness
- **Accessibility**: Provide text alternatives for video content
- **Training materials**: Create study guides from instructional videos
- **Executive summaries**: Distill long meetings/presentations for stakeholders

### 2.2 Chapter Detection & Summaries

**Detection Method**:

Nova analyzes multimodal signals to identify logical chapter boundaries:

1. **Topic Transitions**: Detects when discussion shifts from one subject to another based on semantic content analysis
2. **Visual Scene Changes**: Identifies significant changes in visual setting, background, or on-screen content
3. **Speaker Changes**: Recognizes when different speakers begin talking (multi-speaker videos)
4. **Audio Cues**: Detects phrases like "next, let's talk about...", "moving on to...", "in conclusion..."
5. **Temporal Structure**: Understands natural breakpoints in narrative flow

Unlike Rekognition's technical segment detection (which uses shot/scene boundaries based on pixel changes), Nova performs semantic segmentation based on content meaning. This results in chapters that align with how humans naturally divide content into logical sections.

**Chapter Schema**:
```json
{
  "chapters": [
    {
      "index": 1,
      "title": "Introduction and Equipment Overview",
      "start_time": "00:00",
      "start_seconds": 0.0,
      "end_time": "03:00",
      "end_seconds": 180.5,
      "duration": "03:00",
      "duration_seconds": 180.5,
      "summary": "Instructor introduces the tutorial topic and showcases the camera equipment, lenses, and lighting gear that will be used throughout the session.",
      "key_points": [
        "Course overview and learning objectives",
        "Equipment introduction (Canon EOS R5, 50mm f/1.8 lens)",
        "Setup and preparation"
      ],
      "identified_elements": {
        "objects": ["camera", "lens", "tripod"],
        "people_count": 1,
        "topics": ["photography equipment", "tutorial introduction"],
        "mentioned_equipment": ["Canon EOS R5", "50mm lens"]
      }
    },
    {
      "index": 2,
      "title": "Camera Settings for Portraits",
      "start_time": "03:00",
      "start_seconds": 180.5,
      "end_time": "08:40",
      "end_seconds": 520.0,
      "duration": "05:40",
      "duration_seconds": 339.5,
      "summary": "Detailed explanation of optimal camera settings for portrait photography including aperture (f/1.8-f/2.8 for shallow depth of field), shutter speed considerations (1/125s or faster), and ISO settings for different lighting conditions.",
      "key_points": [
        "Aperture selection for depth of field control",
        "Shutter speed to avoid motion blur",
        "ISO management for noise control"
      ],
      "identified_elements": {
        "objects": ["camera display", "settings menu"],
        "people_count": 1,
        "topics": ["aperture", "shutter speed", "ISO", "exposure triangle"],
        "mentioned_equipment": ["camera settings"]
      }
    }
  ],
  "total_chapters": 2,
  "total_duration": "08:40",
  "detection_method": "semantic_segmentation",
  "model_used": "us.amazon.nova-lite-v1:0"
}
```

**Chapter Detection Prompt**:
```
Analyze this video and segment it into logical chapters based on content transitions and topic changes.

For each chapter, provide:
1. A descriptive title that clearly indicates the chapter's content
2. Start and end timestamps in MM:SS format
3. A brief summary (2-3 sentences) of what happens in that chapter
4. Key points covered (bullet list)
5. Any equipment, objects, or topics specifically discussed

Return the results in JSON format with the following structure:
{
  "chapters": [
    {
      "index": 1,
      "title": "...",
      "start_time": "MM:SS",
      "end_time": "MM:SS",
      "summary": "...",
      "key_points": ["..."],
      "identified_elements": {
        "topics": ["..."],
        "mentioned_equipment": ["..."]
      }
    }
  ]
}

Create chapters that align with natural content divisions. Aim for chapters between 2-10 minutes in length where appropriate.
```

**Comparison with Rekognition Segments**:

| Aspect | Rekognition Segments | Nova Chapters |
|--------|---------------------|---------------|
| **Detection Basis** | Technical (shot/scene detection based on visual changes) | Semantic (content/topic changes based on meaning) |
| **Titles** | None (just timestamps and technical labels like "SHOT", "BLACK_FRAMES") | AI-generated descriptive titles explaining chapter content |
| **Summaries** | None | Detailed per-chapter summaries with key points |
| **Granularity** | Fine (can detect every camera cut, 100+ segments typical) | Coarse (5-15 logical chapters typical for 30-min video) |
| **Timestamp Precision** | Highly precise (millisecond accuracy) | Approximate (±1 second due to 1 FPS sampling) |
| **Audio Consideration** | No (visual only) | Yes (audio + visual multimodal analysis) |
| **Best For** | Video editing, technical analysis, shot-by-shot review | Content navigation, summarization, user-facing features |
| **Use Cases** | Automated editing, thumbnail generation, scene indexing | Table of contents, chapter markers, content discovery |

**When to use each**:

- **Use Rekognition Segments when**:
  - Performing technical video editing or post-production
  - Needing precise shot-level segmentation
  - Generating thumbnails for every scene
  - Detecting technical artifacts (black frames, color bars)
  - Building automated video editing tools

- **Use Nova Chapters when**:
  - Creating user-friendly navigation (like YouTube chapters)
  - Generating table of contents for long videos
  - Building content discovery features
  - Providing semantic search within videos
  - Creating study guides or video summaries
  - Helping users skip to relevant sections

- **Use Both when**:
  - Building professional video platforms
  - Offering both technical and user-facing features
  - Providing editing tools + viewer navigation
  - Maximum insight and flexibility needed

**UI Presentation**:

```html
<!-- Chapter Timeline Visualization -->
<div class="video-chapters-timeline">
  <div class="timeline-bar">
    <div class="chapter" style="left: 0%; width: 20%;" data-chapter="1">
      <span class="chapter-marker">1</span>
      <span class="chapter-title">Introduction</span>
    </div>
    <div class="chapter" style="left: 20%; width: 30%;" data-chapter="2">
      <span class="chapter-marker">2</span>
      <span class="chapter-title">Camera Settings</span>
    </div>
    <!-- More chapters -->
  </div>
</div>

<!-- Chapter List -->
<div class="chapters-list">
  <div class="chapter-item" onclick="jumpToTime(0)">
    <div class="chapter-number">1</div>
    <div class="chapter-content">
      <h5>Introduction and Equipment Overview <span class="timestamp">00:00 - 03:00</span></h5>
      <p class="chapter-summary">Instructor introduces the tutorial topic and showcases equipment...</p>
      <ul class="chapter-topics">
        <li>Course overview and learning objectives</li>
        <li>Equipment introduction</li>
      </ul>
    </div>
  </div>
  <!-- More chapters -->
</div>

<!-- Export as TOC -->
<button onclick="exportChaptersTOC()">Export Table of Contents</button>
```

### 2.3 Element Identification

**Equipment Detection**:

- **Approach**: Nova combines visual object recognition with contextual understanding from audio to identify equipment and tools
- **Categories**:
  - Photography: Cameras, lenses, tripods, lighting equipment
  - Computing: Laptops, monitors, keyboards, tablets
  - Tools: Power tools, hand tools, measuring devices
  - Sports: Athletic equipment, balls, protective gear
  - Musical: Instruments, amplifiers, recording equipment
  - Medical: Diagnostic devices, surgical tools
  - Vehicles: Cars, bikes, heavy machinery

- **Accuracy**: High for common objects (90%+ for well-framed, clearly visible equipment). Accuracy decreases for:
  - Partially obscured objects
  - Similar-looking equipment (e.g., distinguishing camera models)
  - Specialized/rare equipment without additional context
  - Very small objects in frame

- **Example Prompt**:
```
Identify all equipment, tools, and devices visible or mentioned in this video.

For each item, provide:
- Item name (be as specific as possible)
- Category (photography, computing, tools, sports, etc.)
- Time ranges when it's visible or discussed (format: "MM:SS-MM:SS")
- Context: How is it being used? Is it being demonstrated, discussed, or just present?
- Whether it's explicitly discussed (mentioned in audio) vs just visible

Return in JSON format:
{
  "equipment": [
    {
      "name": "Canon EOS R5",
      "category": "photography",
      "time_ranges": ["00:30-03:00", "05:15-08:40"],
      "context": "Primary camera being demonstrated throughout tutorial",
      "discussed": true,
      "visible": true
    }
  ]
}
```

**Object Discussion Analysis**:

Nova's multimodal capabilities enable sophisticated correlation between what's shown and what's said:

1. **Visual Detection**: Identifies objects visible in video frames
2. **Audio Transcription**: Transcribes spoken content
3. **Correlation**: Matches visual objects with audio references
4. **Contextual Understanding**: Determines relationship between objects and discussion

**Example Correlation**:
- **Visual**: Camera equipment visible in frame at 02:30
- **Audio**: Speaker says "this lens is perfect for portrait photography" at 02:32
- **Nova Output**: Identifies camera equipment AND associates it with "portrait photography" topic, marking it as "discussed: true"

This enables understanding of:
- What equipment is being demonstrated vs just present
- Which features/capabilities are being highlighted
- How objects relate to the video's main themes
- Temporal correlation (when object appears vs when it's discussed)

**People & Speaker Detection**:

**Privacy-Friendly Approach**:
- **No facial recognition**: Nova does not identify individuals by name or biometric data
- **Person presence**: Detects number of people in frame
- **Speaker diarization**: Identifies distinct speakers as "Speaker 1", "Speaker 2", etc.
- **GDPR/CCPA compliant**: No PII collection or biometric identification

**Capabilities**:
```json
{
  "people_analysis": {
    "max_count": 2,
    "timeline": [
      {
        "time_range": ["00:00", "03:00"],
        "count": 1,
        "description": "Single person (instructor) speaking to camera"
      },
      {
        "time_range": ["03:00", "15:30"],
        "count": 2,
        "description": "Instructor and model present for portrait demonstration"
      }
    ],
    "speakers": [
      {
        "speaker_id": "Speaker_1",
        "role": "Primary Instructor",
        "speaking_segments": [
          {"start": "00:00", "end": "02:45"},
          {"start": "03:15", "end": "15:30"}
        ],
        "total_speaking_time": "14:60",
        "speaking_percentage": 95.5
      },
      {
        "speaker_id": "Speaker_2",
        "role": "Secondary Speaker",
        "speaking_segments": [
          {"start": "02:45", "end": "03:15"}
        ],
        "total_speaking_time": "00:30",
        "speaking_percentage": 4.5
      }
    ]
  }
}
```

**Output Schema for Identified Elements**:

```json
{
  "identified_elements": {
    "equipment": [
      {
        "name": "Canon EOS R5 DSLR Camera",
        "category": "photography",
        "brand": "Canon",
        "appearances": [
          {
            "start": "00:30",
            "end": "03:00",
            "context": "being introduced and explained",
            "frame_count": 150
          },
          {
            "start": "05:15",
            "end": "12:30",
            "context": "actively being demonstrated with settings shown",
            "frame_count": 435
          }
        ],
        "total_visible_duration": "09:45",
        "discussed": true,
        "mention_count": 12,
        "confidence": "high"
      },
      {
        "name": "50mm f/1.8 Prime Lens",
        "category": "photography",
        "brand": "Canon",
        "appearances": [
          {
            "start": "01:00",
            "end": "12:30",
            "context": "attached to camera, primary lens used",
            "frame_count": 690
          }
        ],
        "total_visible_duration": "11:30",
        "discussed": true,
        "mention_count": 8,
        "confidence": "high"
      }
    ],
    "objects": [
      {
        "name": "Softbox Lighting Kit",
        "category": "lighting",
        "appearances": [
          {
            "start": "06:00",
            "end": "10:30",
            "context": "demonstrating three-point lighting setup"
          }
        ],
        "discussed": true
      },
      {
        "name": "Gray Backdrop",
        "category": "studio_equipment",
        "appearances": [
          {
            "start": "03:00",
            "end": "15:30",
            "context": "background for portrait session"
          }
        ],
        "discussed": false
      }
    ],
    "people": {
      "max_count": 2,
      "timeline": [
        {"time_range": ["00:00", "03:00"], "count": 1},
        {"time_range": ["03:00", "15:30"], "count": 2}
      ],
      "roles_identified": ["instructor", "model"]
    },
    "topics_discussed": [
      {
        "topic": "Aperture and depth of field",
        "time_ranges": [
          ["02:00", "04:30"]
        ],
        "mentions": 18,
        "importance": "high",
        "related_equipment": ["50mm f/1.8 lens", "camera settings"],
        "keywords": ["f-stop", "bokeh", "background blur", "shallow depth"]
      },
      {
        "topic": "Three-point lighting setup",
        "time_ranges": [
          ["06:00", "10:30"]
        ],
        "mentions": 24,
        "importance": "high",
        "related_equipment": ["softbox kit", "key light", "fill light", "back light"],
        "keywords": ["key light", "fill light", "rim light", "lighting ratio"]
      },
      {
        "topic": "Rule of thirds composition",
        "time_ranges": [
          ["11:00", "13:00"]
        ],
        "mentions": 10,
        "importance": "medium",
        "related_equipment": ["camera grid overlay"],
        "keywords": ["composition", "grid lines", "placement", "balance"]
      }
    ],
    "metadata": {
      "analysis_timestamp": "2025-12-18T10:30:00Z",
      "model_used": "us.amazon.nova-lite-v1:0",
      "video_duration": "15:30",
      "total_equipment_identified": 6,
      "total_topics_extracted": 8
    }
  }
}
```

### 2.4 Required Nova Response Schema (NovaVideoIndex)

**Purpose**: Define a standardized JSON schema that Nova must return for all video analysis, ensuring consistent structured data for storage, search, and indexing. This schema is designed for:
- Comprehensive video indexing for **pool and landscape water feature videos**
- Full-text and semantic search across video libraries
- Segment-level granularity for precise content navigation
- Rich metadata for training, quality assessment, and content discovery
- Support for installation, showcase, maintenance, design, and marketing videos

**Schema Version**: 1.1

**Video Content Types Supported**:

| Content Type | Description | Examples |
|--------------|-------------|----------|
| `installation` | Construction and building process | Boulder placement, plumbing, excavation |
| `showcase` | Finished feature demonstrations | Completed waterfall running, night lighting |
| `maintenance` | Repair, cleaning, troubleshooting | Pump replacement, leak repair, winterization |
| `design` | Planning and design discussions | 3D renders, site surveys, client meetings |
| `product_demo` | Product features and capabilities | Kit unboxing, equipment operation |
| `before_after` | Transformation comparisons | Project progress, renovations |
| `training` | Educational and how-to content | Technique tutorials, best practices |
| `marketing` | Sales and promotional content | Company overview, testimonials |
| `timelapse` | Time-compressed footage | Full project build, single day progress |
| `other` | Uncategorized content | |

**JSON Schema Definition**:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/nova-video-index.schema.json",
  "title": "NovaVideoIndex",
  "description": "Schema for indexing pool and landscape water feature videos",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "video_id",
    "duration_sec",
    "overall",
    "segments"
  ],
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.1"
    },
    "video_id": {
      "type": "string",
      "description": "Stable ID you provide (filename hash, UUID, etc.)."
    },
    "source_uri": {
      "type": ["string", "null"],
      "description": "S3 URI (or internal ref). Optional for local-first workflows."
    },
    "duration_sec": {
      "type": "integer",
      "minimum": 1
    },

    "overall": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "one_sentence_summary",
        "detailed_summary",
        "video_content_type",
        "primary_topics",
        "visual_quality_notes",
        "uncertainties"
      ],
      "properties": {
        "one_sentence_summary": {
          "type": "string",
          "minLength": 10,
          "description": "High-level summary in plain English."
        },
        "detailed_summary": {
          "type": "string",
          "minLength": 50,
          "description": "A fuller paragraph or two. Describe what happens and what is shown."
        },
        "video_content_type": {
          "type": "string",
          "enum": [
            "installation",
            "showcase",
            "maintenance",
            "design",
            "product_demo",
            "before_after",
            "training",
            "marketing",
            "timelapse",
            "other"
          ],
          "description": "Primary content category of the video."
        },
        "primary_topics": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1,
          "maxItems": 20,
          "description": "High-level searchable topics (e.g., boulder-placement, pump-installation, grotto-lighting, waterfall-design)."
        },
        "water_feature_types": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": [
              "waterfall_natural",
              "waterfall_formal",
              "waterfall_pondless",
              "grotto",
              "slide",
              "stream_creek",
              "spillway_sheer_descent",
              "jump_rock",
              "fountain",
              "bubbler_deck_jets",
              "infinity_edge",
              "beach_entry",
              "fire_water_feature",
              "koi_pond",
              "swim_up_bar",
              "spa_hot_tub",
              "pool_general",
              "landscape_water_feature",
              "other",
              "unknown"
            ]
          },
          "description": "All water feature types visible or discussed in the video."
        },
        "build_type": {
          "type": "string",
          "enum": [
            "shipped_kit_natural_stone",
            "shipped_kit_formal_modern",
            "custom_build_natural_stone",
            "custom_build_formal",
            "prefab_fiberglass",
            "renovation_remodel",
            "mixed_kit_custom",
            "not_applicable",
            "unknown"
          ],
          "description": "Construction approach if identifiable; 'not_applicable' for non-construction videos."
        },
        "project_phase": {
          "type": "string",
          "enum": [
            "design_planning",
            "site_prep",
            "excavation",
            "structural",
            "plumbing_electrical",
            "stone_setting",
            "finishing",
            "water_testing",
            "completed",
            "maintenance",
            "multiple_phases",
            "not_applicable"
          ],
          "description": "Primary construction phase shown (or 'not_applicable' for non-construction)."
        },
        "setting_type": {
          "type": "string",
          "enum": [
            "residential_backyard",
            "residential_front_yard",
            "commercial_hotel_resort",
            "commercial_community",
            "commercial_other",
            "public_park",
            "indoor",
            "mixed",
            "unknown"
          ],
          "description": "Type of property/setting where the feature is located."
        },
        "visual_quality_notes": {
          "type": "array",
          "items": { "type": "string" },
          "maxItems": 10,
          "description": "Notes that affect confidence (night footage, shaky cam, occlusions, dust, distance, etc.)."
        },
        "uncertainties": {
          "type": "array",
          "items": { "type": "string" },
          "maxItems": 10,
          "description": "What cannot be confirmed visually."
        }
      }
    },

    "segments": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "segment_id",
          "start_sec",
          "end_sec",
          "title",
          "description",
          "scene_context",
          "actions",
          "objects",
          "equipment_tools",
          "materials",
          "safety_notes",
          "search_tags",
          "confidence"
        ],
        "properties": {
          "segment_id": {
            "type": "string",
            "description": "Unique within the video, e.g., 'S01', 'S02'..."
          },
          "start_sec": { "type": "integer", "minimum": 0 },
          "end_sec": { "type": "integer", "minimum": 1 },

          "title": {
            "type": "string",
            "minLength": 5,
            "description": "Short, searchable title."
          },
          "description": {
            "type": "string",
            "minLength": 40,
            "description": "Detailed description of what is visible and what changes during the segment."
          },

          "scene_context": {
            "type": "object",
            "additionalProperties": false,
            "required": ["location_type", "camera_style"],
            "properties": {
              "location_type": {
                "type": "string",
                "enum": [
                  "jobsite_active",
                  "backyard_pool_area",
                  "front_yard",
                  "commercial_pool",
                  "shop_fabrication",
                  "warehouse_shipping",
                  "showroom",
                  "trade_show",
                  "office_meeting",
                  "underwater",
                  "rooftop",
                  "unknown"
                ]
              },
              "camera_style": {
                "type": "string",
                "enum": [
                  "handheld",
                  "tripod",
                  "drone_aerial",
                  "gopro_action",
                  "underwater_camera",
                  "security_cam",
                  "screen_recording",
                  "phone_vertical",
                  "professional_cinematic",
                  "unknown"
                ]
              },
              "lighting_conditions": {
                "type": "string",
                "enum": [
                  "daylight_sunny",
                  "daylight_overcast",
                  "dusk_dawn",
                  "night_feature_lit",
                  "night_ambient",
                  "indoor_artificial",
                  "mixed",
                  "unknown"
                ],
                "description": "Lighting conditions that may affect visibility."
              },
              "shot_notes": {
                "type": "array",
                "items": { "type": "string" },
                "maxItems": 10,
                "description": "Notable visuals: wide reveal, close-up of joints, slow pan, before/after, timelapse, etc."
              }
            }
          },

          "actions": {
            "type": "array",
            "items": { "type": "string" },
            "minItems": 1,
            "maxItems": 25,
            "description": "Concrete verbs/phrases describing VISIBLE activities."
          },

          "objects": {
            "type": "array",
            "items": { "type": "string" },
            "maxItems": 30,
            "description": "Key visible nouns (boulders, pool coping, spillway lip, piping, etc.)."
          },

          "equipment_tools": {
            "type": "array",
            "items": { "type": "string" },
            "maxItems": 25,
            "description": "Machines and tools visible (excavator, skid steer, mixer, saw, levels, etc.)."
          },

          "materials": {
            "type": "array",
            "items": { "type": "string" },
            "maxItems": 25,
            "description": "Materials visible (stone, mortar, veneer, PVC, fittings, rebar, etc.)."
          },

          "people_activity": {
            "type": "array",
            "items": { "type": "string" },
            "maxItems": 10,
            "description": "Non-identifying descriptions only (e.g., 'two installers positioning stone')."
          },

          "water_feature_types": {
            "type": "array",
            "items": { "type": "string" },
            "maxItems": 8,
            "description": "Water features visible in this specific segment."
          },

          "water_state": {
            "type": "string",
            "enum": [
              "water_running",
              "water_off",
              "filling",
              "draining",
              "no_water_installed",
              "under_construction",
              "frozen",
              "not_visible"
            ],
            "description": "State of water in the feature during this segment."
          },

          "safety_notes": {
            "type": "array",
            "items": { "type": "string" },
            "maxItems": 10,
            "description": "Visible hazards (lifting, wet surfaces, power tools, excavation edges)."
          },

          "search_tags": {
            "type": "array",
            "items": { "type": "string" },
            "minItems": 5,
            "maxItems": 40,
            "description": "Short tags for filtering/search. Mix of topics, tools, phases, environment."
          },

          "confidence": {
            "type": "object",
            "additionalProperties": false,
            "required": ["overall", "notes"],
            "properties": {
              "overall": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Model's confidence in segment description accuracy."
              },
              "notes": {
                "type": "array",
                "items": { "type": "string" },
                "maxItems": 5,
                "description": "Why confidence is lower/higher."
              }
            }
          }
        }
      }
    }
  }
}
```

**Production Prompt for NovaVideoIndex Output**:

The following prompt is optimized for pool and landscape water feature videos of all types (installation, showcase, maintenance, design, marketing, etc.) and produces consistent, searchable output conforming to the NovaVideoIndex schema v1.1.

```
You are analyzing a video for a pool and landscape water feature company.
This video may show installation, finished features, maintenance, design, marketing, or other content.
Your task is to create a comprehensive, searchable index of what is visible.

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════════
Return ONLY valid JSON conforming to the NovaVideoIndex schema.
- No markdown code fences
- No explanatory text before or after
- No comments within the JSON

═══════════════════════════════════════════════════════════════════════════════
VIDEO METADATA
═══════════════════════════════════════════════════════════════════════════════
video_id: "{{VIDEO_ID}}"
source_uri: "{{SOURCE_URI}}"
duration_sec: {{DURATION_SEC}}

═══════════════════════════════════════════════════════════════════════════════
OVERALL SECTION REQUIREMENTS
═══════════════════════════════════════════════════════════════════════════════

one_sentence_summary:
- Single sentence, 15-30 words
- Format varies by content type:
  - Installation: "[Process] of [feature type] at [location type] showing [key activities]"
  - Showcase: "[Feature type] at [location] featuring [key visual elements]"
  - Maintenance: "[Repair/maintenance activity] on [feature type] demonstrating [technique]"
  - Marketing: "[Company/product] overview showing [key selling points]"
- Examples:
  - "Installation of a natural stone waterfall at a residential pool showing boulder placement and plumbing connections."
  - "Completed grotto with fiber optic lighting at a resort pool featuring nighttime showcase."
  - "Pump replacement and leak repair on a pondless waterfall demonstrating diagnostic process."

detailed_summary:
- 2-4 sentences, 50-150 words
- Adapt focus based on video_content_type:
  - Installation: Construction methods, phases visible, techniques
  - Showcase: Visual features, design elements, ambiance
  - Maintenance: Problem identification, repair process, outcome
  - Design: Plans discussed, client requirements, proposed solutions
  - Marketing: Company capabilities, featured projects, value proposition

video_content_type (REQUIRED):
- installation: Active construction/building process
- showcase: Finished feature demonstration (often with water running)
- maintenance: Repair, cleaning, troubleshooting, winterization
- design: Planning, 3D renders, site surveys, client meetings
- product_demo: Kit unboxing, equipment operation, product features
- before_after: Transformation comparisons, renovation progress
- training: How-to tutorials, technique demonstrations, best practices
- marketing: Company overview, testimonials, promotional content
- timelapse: Time-compressed footage of any activity
- other: Doesn't fit above categories

primary_topics (1-20 items):
- Use lowercase, hyphenated phrases
- Include: activity-type, feature-type, techniques, materials-category, phase
- Good: "boulder-placement", "pump-repair", "grotto-lighting", "waterfall-design", "night-showcase"
- Bad: "work", "stuff", "things", "video"

water_feature_types:
- Select ALL that apply from expanded list:
  - Waterfalls: waterfall_natural, waterfall_formal, waterfall_pondless
  - Pool features: grotto, slide, jump_rock, swim_up_bar, infinity_edge, beach_entry
  - Water effects: spillway_sheer_descent, fountain, bubbler_deck_jets, fire_water_feature
  - Other: stream_creek, koi_pond, spa_hot_tub, pool_general, landscape_water_feature
  - unknown: Cannot determine
- If no water feature visible, use ["pool_general"] or ["landscape_water_feature"]

build_type:
- shipped_kit_natural_stone: Pre-fabricated rock panels, numbered pieces, assembly
- shipped_kit_formal_modern: Clean lines, manufactured materials, modular components
- custom_build_natural_stone: Raw boulders, on-site shaping, unique placement
- custom_build_formal: Custom but clean/modern design
- prefab_fiberglass: Pre-molded fiberglass shells
- renovation_remodel: Updating/modifying existing feature
- mixed_kit_custom: Combination of kit and custom elements
- not_applicable: Showcase, maintenance, marketing videos where build type not relevant
- unknown: Cannot determine from visuals

project_phase:
- design_planning, site_prep, excavation, structural, plumbing_electrical
- stone_setting, finishing, water_testing, completed, maintenance
- multiple_phases: Video shows more than one phase
- not_applicable: Non-construction videos

setting_type:
- residential_backyard, residential_front_yard
- commercial_hotel_resort, commercial_community, commercial_other
- public_park, indoor, mixed, unknown

visual_quality_notes:
- Document issues affecting analysis confidence
- Include: lighting conditions, camera stability, obstructions, distance, dust/debris, weather
- Example: ["handheld camera with significant shake", "night footage with feature lights only", "drone footage provides excellent overview"]

uncertainties:
- What cannot be confirmed from video alone
- Example: ["specific mortar mix ratio", "pump model", "whether feature is new or renovated"]

═══════════════════════════════════════════════════════════════════════════════
SEGMENT REQUIREMENTS
═══════════════════════════════════════════════════════════════════════════════

SEGMENTATION RULES:
1. Segments MUST be ordered chronologically
2. Segments MUST NOT overlap: each segment's end_sec equals next segment's start_sec
3. Segments MUST cover full video: first start_sec = 0, last end_sec = video duration
4. Segment duration: aim for 30-180 seconds each (adjust based on activity changes)
5. Split on: major activity change, location change, new phase of work, camera angle shift with new subject

segment_id:
- Format: "S01", "S02", ... "S99"
- Sequential, zero-padded

start_sec / end_sec:
- Integer seconds
- start_sec is inclusive, end_sec is exclusive
- Example: start_sec=0, end_sec=45 means 0:00 to 0:44

title (5+ characters):
- Short, searchable phrase (3-8 words)
- Format: "[Action] [Object/Feature]" or "[Phase/Stage] [Description]"
- Good: "Boulder Placement on Upper Tier", "Plumbing Connection at Spillway"
- Bad: "Work Being Done", "Part 2", "Continued"

description (40+ characters):
- 2-4 sentences describing VISIBLE actions and changes
- Include: what workers are doing, what changes from start to end, techniques observed
- Be specific: "Two workers position a 3-foot moss rock on the upper waterfall tier using a mini excavator"
- Not: "Workers are doing construction work on the project"

scene_context:
  location_type:
  - jobsite_active: Active construction site, excavation, heavy equipment
  - backyard_pool_area: Residential pool setting (construction or finished)
  - front_yard: Front of property (landscape features)
  - commercial_pool: Hotel, resort, or community pool
  - shop_fabrication: Indoor workshop, panel assembly, pre-fabrication
  - warehouse_shipping: Storage, packing, loading areas
  - showroom: Display area, finished features for demonstration
  - trade_show: Convention/expo booth
  - office_meeting: Indoor design/sales meeting
  - underwater: Shot from underwater perspective
  - rooftop: Rooftop pool or feature
  - unknown: Cannot determine

  camera_style:
  - handheld: Visible shake, walking movement, POV perspective
  - tripod: Stable, fixed position, minimal movement
  - drone_aerial: Aerial perspective, smooth sweeping movements
  - gopro_action: Wide angle, mounted perspective
  - underwater_camera: Shot from below water surface
  - security_cam: Fixed angle, low quality, continuous
  - screen_recording: Computer screen, software interface
  - phone_vertical: Vertical video from smartphone
  - professional_cinematic: High production value, smooth movements
  - unknown: Cannot determine

  lighting_conditions:
  - daylight_sunny: Bright outdoor, clear shadows
  - daylight_overcast: Outdoor, diffused light
  - dusk_dawn: Golden hour or blue hour lighting
  - night_feature_lit: Nighttime with pool/feature lights on
  - night_ambient: Nighttime with minimal lighting
  - indoor_artificial: Indoor with artificial lights
  - mixed: Multiple lighting conditions in segment
  - unknown: Cannot determine

  shot_notes (optional):
  - Notable cinematography: "wide establishing shot", "close-up of mortar joint", "time-lapse", "before/after comparison", "slow pan across finished feature", "drone reveal", "underwater perspective"

water_state (per segment):
  - water_running: Feature actively operating with water flowing
  - water_off: Water feature exists but not running
  - filling: Pool/feature being filled with water
  - draining: Water being drained
  - no_water_installed: Construction phase before water system operational
  - under_construction: Feature visibly incomplete
  - frozen: Winterized or ice present
  - not_visible: Water state cannot be determined

actions (1-25 items):
- Present participle verb phrases describing VISIBLE activities
- Be specific to construction/installation
- Good: "setting boulders with excavator", "troweling mortar into joints", "connecting PVC fittings", "leveling stone with rubber mallet"
- Bad: "working", "doing stuff", "construction"

objects (0-30 items):
- Visible nouns, specific to what's on screen
- Include: rocks/boulders, water features, pool components, structural elements
- Good: "moss rock boulder", "spillway lip", "skimmer box", "rebar grid", "pump vault"
- Bad: "thing", "item", "stuff"

equipment_tools (0-25 items):
- Machines and hand tools VISIBLE in frame
- Good: "mini excavator", "concrete mixer", "trowel", "level", "grinder", "wet saw", "forklift"
- Include brand/model if clearly visible

materials (0-25 items):
- Construction materials VISIBLE or being used
- Good: "natural stone", "mortar", "PVC pipe", "rebar", "concrete", "foam sealant", "waterproofing membrane"
- Be specific: "2-inch PVC" not just "pipe"

people_activity (0-10 items):
- NON-IDENTIFYING descriptions only
- Good: "two workers positioning boulder", "operator in excavator cab", "person applying mortar"
- Bad: "John Smith", "the homeowner", personal descriptions

safety_notes (0-10 items):
- Visible hazards or safety considerations
- Good: "heavy lifting without visible back support", "worker near excavation edge", "no hard hats visible", "wet surface near pool"
- Only note what is VISIBLE, not assumed

search_tags (5-40 items):
- Short, lowercase, hyphenated keywords for search/filtering
- Mix of: activity-type, material-type, tool-name, phase-name, feature-type, technique-name
- Good: "boulder-setting", "waterfall", "excavator", "mortar-work", "upper-tier", "plumbing", "natural-stone"
- Include synonyms: "rocks" and "boulders", "pool" and "swimming-pool"

confidence:
  overall (0.0-1.0):
  - 0.9-1.0: Clear video, good lighting, close views, confident in all details
  - 0.7-0.9: Good video, some minor issues, confident in main activities
  - 0.5-0.7: Moderate issues (distance, lighting, shake), some uncertainty
  - 0.3-0.5: Significant issues, major uncertainty in details
  - 0.0-0.3: Poor quality, mostly guessing

  notes (0-5 items):
  - Explain factors affecting confidence
  - Good: ["camera shake reduces detail clarity", "dust obscures stone texture", "excellent close-up views of plumbing connections"]

═══════════════════════════════════════════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════════════════════════════════════════

1. VISUAL EVIDENCE ONLY
   - Describe only what is VISIBLE in the video
   - Do not infer customer names, addresses, or personal information
   - Do not guess at off-screen activities

2. WATER FEATURE DOMAIN FOCUS
   - Use industry-appropriate terminology for pools and water features
   - Adapt focus based on video_content_type:
     * Installation: techniques, materials, tools, phases, safety
     * Showcase: visual features, lighting, design elements, ambiance
     * Maintenance: diagnostic process, repair techniques, equipment
     * Marketing: company capabilities, value propositions
   - Think like someone building a searchable video library

3. SEARCHABILITY PRIORITY
   - Every field should help someone FIND this content later
   - Ask: "Would a pool contractor, designer, or homeowner search for this term?"
   - Include specific AND general terms (both "mini excavator" and "heavy equipment")
   - Include terms for feature type, activity type, and visual characteristics

4. TEMPORAL ACCURACY
   - Timestamps must be accurate to ±3 seconds
   - When uncertain, round to nearest 5-second boundary
   - Note timestamp uncertainty in confidence.notes

5. SEGMENT COMPLETENESS
   - Every second of video must belong to exactly one segment
   - No gaps, no overlaps
   - Final segment's end_sec must equal video duration

6. CONTENT TYPE AWARENESS
   - Set video_content_type accurately - this drives downstream processing
   - Showcase videos focus on finished features, not construction
   - Maintenance videos focus on repair process, not aesthetics
   - Timelapse videos may span multiple phases

═══════════════════════════════════════════════════════════════════════════════
EXAMPLE OUTPUT STRUCTURE
═══════════════════════════════════════════════════════════════════════════════

EXAMPLE 1: Installation Video

{
  "schema_version": "1.1",
  "video_id": "abc123",
  "source_uri": "s3://bucket/video.mp4",
  "duration_sec": 180,
  "overall": {
    "one_sentence_summary": "Installation of natural stone waterfall at residential pool showing boulder placement and mortar work.",
    "detailed_summary": "This video documents the construction of a three-tier natural stone waterfall. Workers use a mini excavator to position large moss rock boulders, followed by hand placement of smaller accent stones. Mortar is applied between joints for stability. The final portion shows water testing of the completed feature.",
    "video_content_type": "installation",
    "primary_topics": ["waterfall-installation", "boulder-placement", "mortar-work", "natural-stone", "residential-pool"],
    "water_feature_types": ["waterfall_natural"],
    "build_type": "custom_build_natural_stone",
    "project_phase": "stone_setting",
    "setting_type": "residential_backyard",
    "visual_quality_notes": ["good lighting throughout", "some camera shake during walking segments"],
    "uncertainties": ["specific mortar mix used", "boulder weights"]
  },
  "segments": [
    {
      "segment_id": "S01",
      "start_sec": 0,
      "end_sec": 60,
      "title": "Site Overview and Boulder Staging",
      "description": "Opening shot shows the pool area with excavator positioned near boulder pile. Camera pans across staged moss rocks of varying sizes. Workers discuss placement strategy.",
      "scene_context": {
        "location_type": "backyard_pool_area",
        "camera_style": "handheld",
        "lighting_conditions": "daylight_sunny",
        "shot_notes": ["wide establishing shot", "pan across materials"]
      },
      "actions": ["surveying staged materials", "discussing placement plan", "positioning excavator"],
      "objects": ["moss rock boulders", "mini excavator", "pool coping", "staged stone pile"],
      "equipment_tools": ["mini excavator", "rigging straps"],
      "materials": ["natural moss rock", "limestone boulders"],
      "people_activity": ["two workers reviewing stone pile", "excavator operator in cab"],
      "water_feature_types": ["waterfall_natural"],
      "water_state": "under_construction",
      "safety_notes": ["workers near heavy equipment"],
      "search_tags": ["site-prep", "boulder-staging", "excavator", "moss-rock", "waterfall", "material-staging"],
      "confidence": {
        "overall": 0.85,
        "notes": ["clear wide shots", "audio discussion provides context"]
      }
    }
  ]
}

═══════════════════════════════════════════════════════════════════════════════

EXAMPLE 2: Showcase Video (Nighttime Feature)

{
  "schema_version": "1.1",
  "video_id": "xyz789",
  "source_uri": "s3://bucket/grotto-night.mp4",
  "duration_sec": 120,
  "overall": {
    "one_sentence_summary": "Nighttime showcase of completed grotto with fiber optic lighting at luxury residential pool featuring underwater and above-water perspectives.",
    "detailed_summary": "This video presents a finished grotto installation at night, highlighting the custom fiber optic star ceiling, LED color-changing effects, and waterfall cascade. Camera captures multiple angles including drone aerial, poolside tripod, and underwater GoPro footage. The grotto interior shows built-in seating and dramatic uplighting on the natural stone walls.",
    "video_content_type": "showcase",
    "primary_topics": ["grotto-lighting", "night-showcase", "fiber-optics", "led-effects", "luxury-pool", "finished-feature"],
    "water_feature_types": ["grotto", "waterfall_natural"],
    "build_type": "not_applicable",
    "project_phase": "completed",
    "setting_type": "residential_backyard",
    "visual_quality_notes": ["professional cinematic quality", "night footage with excellent feature lighting"],
    "uncertainties": ["LED brand/model", "exact fiber optic count"]
  },
  "segments": [
    {
      "segment_id": "S01",
      "start_sec": 0,
      "end_sec": 30,
      "title": "Drone Reveal of Illuminated Pool",
      "description": "Aerial drone footage reveals the entire backyard pool area at dusk. The grotto glows with blue interior lighting as the drone descends toward the water. Pool lights transition through colors visible from above.",
      "scene_context": {
        "location_type": "backyard_pool_area",
        "camera_style": "drone_aerial",
        "lighting_conditions": "dusk_dawn",
        "shot_notes": ["dramatic reveal shot", "descending approach", "color transitions visible"]
      },
      "actions": ["drone descending", "lights cycling colors", "water reflecting lights"],
      "objects": ["swimming pool", "grotto entrance", "waterfall", "pool deck", "landscape lighting"],
      "equipment_tools": [],
      "materials": ["natural stone", "fiber optic ceiling", "led fixtures"],
      "people_activity": [],
      "water_feature_types": ["grotto", "waterfall_natural"],
      "water_state": "water_running",
      "safety_notes": [],
      "search_tags": ["drone-shot", "night-lighting", "grotto", "led", "reveal-shot", "luxury", "color-changing", "aerial"],
      "confidence": {
        "overall": 0.95,
        "notes": ["excellent visibility", "professional footage quality"]
      }
    },
    {
      "segment_id": "S02",
      "start_sec": 30,
      "end_sec": 70,
      "title": "Grotto Interior Fiber Optic Ceiling",
      "description": "Camera enters the grotto showing the custom fiber optic star ceiling effect. Hundreds of tiny lights create a starfield pattern on the curved ceiling. Built-in stone bench seating visible along the walls with subtle uplighting.",
      "scene_context": {
        "location_type": "backyard_pool_area",
        "camera_style": "handheld",
        "lighting_conditions": "night_feature_lit",
        "shot_notes": ["interior walkthrough", "ceiling detail shots", "seating area"]
      },
      "actions": ["walking into grotto", "panning across ceiling", "showcasing seating"],
      "objects": ["fiber optic ceiling", "stone seating", "grotto walls", "uplighting", "water entry point"],
      "equipment_tools": [],
      "materials": ["fiber optic strands", "natural stone veneer", "led strip lighting", "concrete bench"],
      "people_activity": [],
      "water_feature_types": ["grotto"],
      "water_state": "water_running",
      "safety_notes": [],
      "search_tags": ["grotto-interior", "fiber-optic", "star-ceiling", "built-in-seating", "uplighting", "ambient-lighting"],
      "confidence": {
        "overall": 0.90,
        "notes": ["low light but features well-lit", "some dark areas in corners"]
      }
    }
  ]
}

Now analyze the provided video and return the complete NovaVideoIndex JSON.
```

**Template Variables**:
Replace these placeholders before sending to Nova:
- `{{VIDEO_ID}}`: Unique identifier (filename hash, UUID, or database ID)
- `{{SOURCE_URI}}`: S3 URI or file path (optional, can be null)
- `{{DURATION_SEC}}`: Video duration in seconds (integer)

**Prompt Variations by Video Length**:

| Video Duration | Segment Count Target | Segment Duration | Notes |
|----------------|---------------------|------------------|-------|
| < 2 minutes | 2-4 segments | 15-60 sec | Fine-grained for short clips |
| 2-5 minutes | 3-8 segments | 30-90 sec | Standard segmentation |
| 5-15 minutes | 5-15 segments | 45-120 sec | Balance detail vs count |
| 15-30 minutes | 10-20 segments | 60-180 sec | Avoid over-segmentation |
| > 30 minutes | Use chunking | 60-180 sec | Process via chunk strategy |

**Python Implementation**:

```python
def build_nova_video_index_prompt(
    video_id: str,
    duration_sec: int,
    source_uri: str = None
) -> str:
    """
    Build production prompt for NovaVideoIndex extraction.

    Args:
        video_id: Unique video identifier
        duration_sec: Video duration in seconds
        source_uri: Optional S3 URI or file path

    Returns:
        Complete prompt string with variables substituted
    """

    PROMPT_TEMPLATE = '''You are analyzing a construction/installation video for a water feature company.
Your task is to create a comprehensive, searchable index of what is visible.

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════════
Return ONLY valid JSON conforming to the NovaVideoIndex schema.
- No markdown code fences
- No explanatory text before or after
- No comments within the JSON

═══════════════════════════════════════════════════════════════════════════════
VIDEO METADATA
═══════════════════════════════════════════════════════════════════════════════
video_id: "{video_id}"
source_uri: {source_uri_str}
duration_sec: {duration_sec}

... [full prompt template continues - see documentation above] ...

Now analyze the provided video and return the complete NovaVideoIndex JSON.'''

    source_uri_str = f'"{source_uri}"' if source_uri else 'null'

    return PROMPT_TEMPLATE.format(
        video_id=video_id,
        source_uri_str=source_uri_str,
        duration_sec=duration_sec
    )


def validate_nova_video_index(response: dict) -> tuple[bool, list[str]]:
    """
    Validate Nova response against NovaVideoIndex schema.

    Args:
        response: Parsed JSON response from Nova

    Returns:
        Tuple of (is_valid, list of validation errors)
    """
    errors = []

    # Check required top-level fields
    required_fields = ['schema_version', 'video_id', 'duration_sec', 'overall', 'segments']
    for field in required_fields:
        if field not in response:
            errors.append(f"Missing required field: {field}")

    if errors:
        return False, errors

    # Validate schema version
    if response['schema_version'] != '1.0':
        errors.append(f"Invalid schema_version: {response['schema_version']}")

    # Validate overall section
    overall = response.get('overall', {})
    overall_required = ['one_sentence_summary', 'detailed_summary', 'primary_topics',
                        'visual_quality_notes', 'uncertainties']
    for field in overall_required:
        if field not in overall:
            errors.append(f"Missing overall.{field}")

    # Validate segments
    segments = response.get('segments', [])
    if not segments:
        errors.append("No segments provided")
    else:
        # Check segment ordering and coverage
        prev_end = 0
        for i, seg in enumerate(segments):
            seg_id = seg.get('segment_id', f'segment_{i}')

            # Check required segment fields
            seg_required = ['segment_id', 'start_sec', 'end_sec', 'title', 'description',
                          'scene_context', 'actions', 'objects', 'equipment_tools',
                          'materials', 'safety_notes', 'search_tags', 'confidence']
            for field in seg_required:
                if field not in seg:
                    errors.append(f"{seg_id}: missing {field}")

            # Check temporal consistency
            start = seg.get('start_sec', 0)
            end = seg.get('end_sec', 0)

            if start != prev_end:
                errors.append(f"{seg_id}: gap or overlap - expected start_sec={prev_end}, got {start}")

            if end <= start:
                errors.append(f"{seg_id}: end_sec ({end}) must be > start_sec ({start})")

            prev_end = end

            # Check description length
            desc = seg.get('description', '')
            if len(desc) < 40:
                errors.append(f"{seg_id}: description too short ({len(desc)} chars, min 40)")

            # Check search_tags count
            tags = seg.get('search_tags', [])
            if len(tags) < 5:
                errors.append(f"{seg_id}: too few search_tags ({len(tags)}, min 5)")

        # Check final segment covers video duration
        duration = response.get('duration_sec', 0)
        if prev_end != duration:
            errors.append(f"Segments don't cover full duration: last end_sec={prev_end}, duration={duration}")

    return len(errors) == 0, errors
```

**Error Handling for Invalid Responses**:

```python
def process_nova_response(raw_response: str, video_id: str, duration_sec: int) -> dict:
    """
    Process and validate Nova response, with retry logic for common issues.
    """
    import json
    import re

    # Strip markdown code fences if present (common Nova mistake)
    cleaned = raw_response.strip()
    if cleaned.startswith('```'):
        # Remove ```json and trailing ```
        cleaned = re.sub(r'^```(?:json)?\n?', '', cleaned)
        cleaned = re.sub(r'\n?```$', '', cleaned)

    # Parse JSON
    try:
        response = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {e}")

    # Validate against schema
    is_valid, errors = validate_nova_video_index(response)

    if not is_valid:
        # Log errors for debugging
        logger.warning(f"Nova response validation errors for {video_id}: {errors}")

        # Attempt auto-fixes for common issues
        response = attempt_auto_fix(response, duration_sec, errors)

        # Re-validate
        is_valid, errors = validate_nova_video_index(response)
        if not is_valid:
            raise ValueError(f"Nova response failed validation: {errors}")

    return response


def attempt_auto_fix(response: dict, duration_sec: int, errors: list) -> dict:
    """
    Attempt to auto-fix common Nova response issues.
    """
    # Fix segment coverage gaps
    segments = response.get('segments', [])
    if segments:
        # Ensure first segment starts at 0
        segments[0]['start_sec'] = 0

        # Ensure continuous coverage
        for i in range(1, len(segments)):
            segments[i]['start_sec'] = segments[i-1]['end_sec']

        # Ensure last segment ends at duration
        segments[-1]['end_sec'] = duration_sec

    return response
```

**Database Storage**:
- The complete NovaVideoIndex JSON is stored in the `nova_jobs.elements_result` column
- Individual segments can be indexed separately for granular search
- Embeddings are generated from segment descriptions and search_tags for semantic search

**Indexing Strategy**:
- **Full-text search**: Index `primary_topics`, `search_tags`, `title`, and `description` fields
- **Faceted filtering**: Use `water_feature_types`, `kit_or_build_type`, `location_type`, `equipment_tools`
- **Vector search**: Generate embeddings from combined `title + description + search_tags` per segment
- **Time-based navigation**: Use `start_sec`/`end_sec` for video player integration

---

*End of Part 1: Service Capabilities & Feature Design*

---

## 3. Long Video Handling Strategy

### 3.1 Context Window Analysis

**Nova Model Token Limits and Video Duration Equivalents**:

| Model | Max Tokens | Approx Video Duration | Calculation Basis |
|-------|------------|----------------------|-------------------|
| **Nova Micro** | 128,000 | ~12 minutes | 128K tokens ≈ 720 frames @ 1 FPS |
| **Nova Lite** | 300,000 | ~30 minutes | 300K tokens ≈ 1,800 frames @ 1 FPS |
| **Nova Pro** | 300,000 | ~30 minutes | 300K tokens ≈ 1,800 frames @ 1 FPS |
| **Nova Premier** | 1,000,000 | ~90 minutes | 1M tokens ≈ 5,400 frames @ 1 FPS |

**Token Consumption Breakdown**:

Video content is converted to tokens through multiple components:
- **Visual frames**: ~100-200 tokens per frame (varies by complexity)
- **Audio transcription**: ~1 token per 0.75 words (standard tokenization)
- **Metadata**: Timestamps, frame numbers, technical data
- **Prompt**: User's analysis request
- **System context**: Model instructions and formatting

**Example for 30-minute video**:
- Frames: 1,800 frames × 150 tokens/frame = 270,000 tokens
- Audio: ~4,500 words × 1.33 tokens/word = ~6,000 tokens
- Metadata + Prompt: ~2,000 tokens
- **Total**: ~278,000 tokens (fits in Lite/Pro 300K limit)

**Chunking Necessity**:

Videos exceeding context limits must be split into chunks:
- **60-minute video with Nova Lite**: Requires ~2-3 chunks
- **2-hour video with Nova Pro**: Requires ~4-5 chunks
- **4-hour video with Nova Premier**: Requires ~2-3 chunks

Each chunk needs overlap to preserve context across boundaries and prevent information loss at transition points.

### 3.2 Chunking Architecture

**Recommended Chunk Sizes**:

| Model | Max Context | Recommended Chunk Duration | Overlap Duration | Effective Content per Chunk |
|-------|-------------|---------------------------|------------------|------------------------------|
| **Nova Micro** | 128K tokens | 10 minutes | 60 seconds (10%) | 9 minutes |
| **Nova Lite** | 300K tokens | 25 minutes | 150 seconds (10%) | 22.5 minutes |
| **Nova Pro** | 300K tokens | 25 minutes | 150 seconds (10%) | 22.5 minutes |
| **Nova Premier** | 1M tokens | 80 minutes | 480 seconds (10%) | 72 minutes |

**Overlap Strategy Rationale**:

**Why 10% Overlap?**
1. **Context Preservation**: Ensures events/discussions spanning chunk boundaries aren't lost
2. **Chapter Continuity**: Allows chapters starting near end of one chunk to be fully captured in next
3. **Minimal Redundancy**: Keeps processing cost reasonable while maintaining quality
4. **Industry Standard**: Aligns with best practices for long-form content segmentation

**How Overlap Works**:
```
Video Timeline: [==========================================================] 60 minutes

Chunk 1:  [===================overlap→]
          0min                    25min  26.5min

Chunk 2:         [←overlap===================overlap→]
                 23.5min          48.5min  50min

Chunk 3:                  [←overlap===================]
                          46.5min          60min

Effective content:  [====] [====] [====] = 9min + 22min + 11min = 42min unique
Redundant content:  overlap regions processed twice
```

**Processing Approach Comparison**:

**Sequential Processing** (Recommended for Chapter Detection):
- **Pros**: Maintains narrative context, can reference previous chunks, coherent aggregation
- **Cons**: Slower (chunks processed one at a time), cannot parallelize
- **Best for**: Chapter detection, summaries requiring narrative flow, topic tracking
- **Implementation**: Process chunk 1 → extract context → process chunk 2 with context → repeat

**Parallel Processing** (Recommended for Element Identification):
- **Pros**: Faster (all chunks process simultaneously), better resource utilization
- **Cons**: No inter-chunk context, requires smarter aggregation, may miss cross-chunk patterns
- **Best for**: Equipment detection, object identification, independent per-chunk summaries
- **Implementation**: Process all chunks concurrently → merge results → deduplicate

**Hybrid Approach** (Optimal):
- Use parallel processing for initial analysis of all chunks
- Use sequential processing for final summary aggregation with context

### 3.3 Implementation Algorithm

**Complete Chunking and Aggregation Pseudocode**:

```python
def analyze_long_video(video_path: str, model: str, analysis_types: List[str]) -> dict:
    """
    Analyze a long video by chunking and aggregating results.

    Args:
        video_path: S3 path to video file (e.g., "s3://bucket/video.mp4")
        model: Nova model to use ('micro', 'lite', 'pro', 'premier')
        analysis_types: List of analysis types ['summary', 'chapters', 'elements']

    Returns:
        dict: Aggregated analysis results
    """

    # STEP 1: Get video metadata
    video_info = get_video_metadata(video_path)
    duration_seconds = video_info['duration']  # e.g., 3600 for 1-hour video

    print(f"Video duration: {duration_seconds}s ({duration_seconds/60:.1f} minutes)")

    # STEP 2: Determine if chunking is needed
    max_duration = get_max_duration_for_model(model)  # e.g., 1800s for Lite

    if duration_seconds <= max_duration:
        print("Video fits in single request, no chunking needed")
        return analyze_video_single(video_path, model, analysis_types)

    print(f"Video exceeds {max_duration}s limit, chunking required")

    # STEP 3: Calculate chunk parameters
    chunk_config = calculate_chunk_parameters(model, duration_seconds)

    chunk_duration = chunk_config['chunk_duration']  # e.g., 1500s (25 min)
    overlap = chunk_config['overlap']  # e.g., 150s (2.5 min)

    print(f"Chunk duration: {chunk_duration}s, Overlap: {overlap}s")

    # STEP 4: Generate chunk boundaries
    chunks = []
    start = 0
    chunk_index = 0

    while start < duration_seconds:
        # Calculate chunk end time
        end = min(start + chunk_duration, duration_seconds)

        # Add overlap to both sides (except first/last)
        overlap_start = max(0, start - overlap)
        overlap_end = min(duration_seconds, end + overlap)

        chunk = {
            'index': chunk_index,
            'core_start': start,  # Non-overlapping portion start
            'core_end': end,      # Non-overlapping portion end
            'overlap_start': overlap_start,  # Actual extraction start (with overlap)
            'overlap_end': overlap_end,      # Actual extraction end (with overlap)
            'duration': overlap_end - overlap_start
        }

        chunks.append(chunk)
        chunk_index += 1
        start = end  # Next chunk starts where this one's core ends

    print(f"Split into {len(chunks)} chunks: {chunks}")

    # STEP 5: Extract video chunks from S3
    chunk_videos = []
    for chunk in chunks:
        print(f"Extracting chunk {chunk['index']}: {chunk['overlap_start']}s - {chunk['overlap_end']}s")

        # Use FFmpeg to extract video segment
        chunk_s3_path = extract_video_segment(
            video_path=video_path,
            start_time=chunk['overlap_start'],
            end_time=chunk['overlap_end'],
            output_key=f"temp/chunks/{video_info['id']}_chunk_{chunk['index']}.mp4"
        )

        chunk_videos.append({
            'chunk': chunk,
            's3_path': chunk_s3_path
        })

    # STEP 6: Process chunks
    chunk_results = []
    previous_context = None  # For sequential processing

    for i, chunk_video in enumerate(chunk_videos):
        chunk = chunk_video['chunk']
        s3_path = chunk_video['s3_path']

        print(f"Processing chunk {chunk['index']} / {len(chunks)}")

        # Build prompt with context from previous chunk
        prompt = build_chunk_prompt(
            analysis_types=analysis_types,
            chunk_index=chunk['index'],
            total_chunks=len(chunks),
            previous_summary=previous_context,
            time_offset=chunk['core_start']  # Adjust timestamps
        )

        # Invoke Nova model
        result = invoke_nova_model(
            model=model,
            video_s3_path=s3_path,
            prompt=prompt
        )

        # Store result with metadata
        chunk_results.append({
            'chunk': chunk,
            'result': result,
            'tokens_used': result['usage']['totalTokens']
        })

        # Extract context for next chunk (sequential processing)
        previous_context = extract_context_for_next_chunk(result, chunk)

        # Clean up temporary chunk file
        delete_s3_object(s3_path)

    # STEP 7: Aggregate results based on analysis type
    aggregated_results = {}

    if 'summary' in analysis_types:
        print("Aggregating summaries...")
        aggregated_results['summary'] = aggregate_summaries(chunk_results, model)

    if 'chapters' in analysis_types:
        print("Merging chapters...")
        aggregated_results['chapters'] = merge_chapters(chunk_results, overlap)

    if 'elements' in analysis_types:
        print("Combining identified elements...")
        aggregated_results['elements'] = combine_elements(chunk_results)

    # STEP 8: Add metadata
    total_tokens = sum(cr['tokens_used'] for cr in chunk_results)
    total_cost = calculate_cost(model, total_tokens)

    aggregated_results['metadata'] = {
        'video_duration': duration_seconds,
        'chunks_processed': len(chunks),
        'model_used': model,
        'total_tokens': total_tokens,
        'estimated_cost': total_cost,
        'processing_strategy': 'chunked_sequential'
    }

    return aggregated_results


def calculate_chunk_parameters(model: str, video_duration: int) -> dict:
    """Calculate optimal chunk size and overlap for given model and video duration."""

    # Base chunk durations (seconds) - leave headroom below max
    CHUNK_CONFIGS = {
        'micro': {'max_duration': 720, 'chunk_duration': 600, 'overlap_pct': 0.10},   # 10 min chunks
        'lite':  {'max_duration': 1800, 'chunk_duration': 1500, 'overlap_pct': 0.10}, # 25 min chunks
        'pro':   {'max_duration': 1800, 'chunk_duration': 1500, 'overlap_pct': 0.10}, # 25 min chunks
        'premier': {'max_duration': 5400, 'chunk_duration': 4800, 'overlap_pct': 0.10} # 80 min chunks
    }

    config = CHUNK_CONFIGS[model]
    chunk_duration = config['chunk_duration']
    overlap = int(chunk_duration * config['overlap_pct'])

    return {
        'chunk_duration': chunk_duration,
        'overlap': overlap,
        'max_duration': config['max_duration']
    }


def build_chunk_prompt(
    analysis_types: List[str],
    chunk_index: int,
    total_chunks: int,
    previous_summary: str = None,
    time_offset: int = 0
) -> str:
    """Build prompt for analyzing a video chunk with context preservation."""

    context_section = ""
    if previous_summary and chunk_index > 0:
        context_section = f"""
CONTEXT FROM PREVIOUS CHUNK:
{previous_summary}

This chunk is a continuation. Reference the above context where relevant.
"""

    chunk_info = f"You are analyzing chunk {chunk_index + 1} of {total_chunks} from a longer video."
    if chunk_index == 0:
        chunk_info += " This is the BEGINNING of the video."
    elif chunk_index == total_chunks - 1:
        chunk_info += " This is the END of the video."
    else:
        chunk_info += " This is a MIDDLE section of the video."

    timestamp_instruction = f"""
IMPORTANT: All timestamps you provide should be relative to the FULL video, not this chunk.
This chunk starts at {time_offset} seconds ({time_offset // 60}:{time_offset % 60:02d}) in the full video.
Add {time_offset} seconds to any timestamps you generate.
"""

    analysis_instructions = ""

    if 'summary' in analysis_types:
        analysis_instructions += """
SUMMARY TASK:
Provide a summary of the content in this chunk. Focus on:
- Main topics and themes discussed
- Key events or demonstrations
- Important information presented
- Continuity with previous content (if applicable)
"""

    if 'chapters' in analysis_types:
        analysis_instructions += f"""
CHAPTER DETECTION TASK:
Identify logical chapters/segments within this chunk. For each chapter:
- Title: Descriptive name
- Start time: MM:SS format (adjusted for full video timeline, starting from {time_offset // 60}:{time_offset % 60:02d})
- End time: MM:SS format
- Summary: Brief description of chapter content

Note: Chapters may start before this chunk or continue beyond it. Include partial chapters.
"""

    if 'elements' in analysis_types:
        analysis_instructions += """
ELEMENT IDENTIFICATION TASK:
Identify all equipment, objects, and topics in this chunk:
- Equipment/tools visible or discussed
- Objects of interest
- Topics being discussed
- For each, provide time ranges when visible/discussed
"""

    full_prompt = f"""
{chunk_info}

{context_section}

{timestamp_instruction}

{analysis_instructions}

Return results in well-structured JSON format.
"""

    return full_prompt


def aggregate_summaries(chunk_results: List[dict], model: str) -> dict:
    """
    Aggregate summaries from multiple chunks into coherent whole.
    Uses Nova itself to merge summaries intelligently.
    """

    # Extract individual chunk summaries
    chunk_summaries = []
    for i, cr in enumerate(chunk_results):
        chunk = cr['chunk']
        summary_text = cr['result']['summary']

        time_label = f"{chunk['core_start']//60}:{chunk['core_start']%60:02d} - {chunk['core_end']//60}:{chunk['core_end']%60:02d}"

        chunk_summaries.append({
            'index': i,
            'time_range': time_label,
            'summary': summary_text
        })

    # Build aggregation prompt
    summaries_text = "\n\n".join([
        f"CHUNK {s['index']+1} ({s['time_range']}):\n{s['summary']}"
        for s in chunk_summaries
    ])

    aggregation_prompt = f"""
You are given summaries from {len(chunk_summaries)} sequential chunks of a video:

{summaries_text}

Create a single, coherent summary of the ENTIRE video that:
1. Integrates all chunks into a unified narrative
2. Identifies overarching themes and structure
3. Highlights the most important points across the full video
4. Maintains logical flow from beginning to end
5. Provides 2-3 comprehensive paragraphs

Do NOT simply concatenate the summaries. Synthesize them into a cohesive whole that someone who hasn't seen the video can understand.
"""

    # Use Nova to create final summary (text-only, no video needed)
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

    response = bedrock.converse(
        modelId=f"us.amazon.{model}-v1:0",
        messages=[
            {
                "role": "user",
                "content": [{"text": aggregation_prompt}]
            }
        ],
        inferenceConfig={
            "maxTokens": 2048,
            "temperature": 0.3  # Lower temp for factual aggregation
        }
    )

    final_summary = response['output']['message']['content'][0]['text']

    return {
        'text': final_summary,
        'depth': 'standard',
        'chunks_aggregated': len(chunk_summaries),
        'word_count': len(final_summary.split())
    }


def merge_chapters(chunk_results: List[dict], overlap: int) -> List[dict]:
    """
    Merge chapters from overlapping chunks, deduplicating chapters in overlap regions.
    """

    all_chapters = []
    seen_timestamps = set()  # Track chapter start times to avoid duplicates

    for cr in chunk_results:
        chunk = cr['chunk']
        chunk_chapters = cr['result'].get('chapters', [])

        for chapter in chunk_chapters:
            # Parse timestamp (assuming MM:SS format or seconds)
            if isinstance(chapter.get('start_seconds'), (int, float)):
                absolute_start = chapter['start_seconds']
            else:
                # Parse MM:SS
                parts = chapter['start_time'].split(':')
                absolute_start = int(parts[0]) * 60 + int(parts[1])

            # Round to nearest second for deduplication
            timestamp_key = round(absolute_start)

            # Check if this chapter was already seen in overlap region
            if timestamp_key in seen_timestamps:
                continue  # Skip duplicate

            # Only include chapters that start within this chunk's CORE region
            # (not in the overlap areas, to avoid duplicates)
            if chunk['core_start'] <= absolute_start < chunk['core_end']:
                seen_timestamps.add(timestamp_key)
                all_chapters.append(chapter)

    # Sort chapters by start time
    all_chapters.sort(key=lambda c: c.get('start_seconds', parse_timestamp(c['start_time'])))

    # Reindex chapters
    for i, chapter in enumerate(all_chapters):
        chapter['index'] = i + 1

    return all_chapters


def combine_elements(chunk_results: List[dict]) -> dict:
    """
    Combine identified elements (equipment, objects, topics) from all chunks.
    Merges duplicate detections and consolidates time ranges.
    """

    combined = {
        'equipment': [],
        'objects': [],
        'topics_discussed': [],
        'people': {'max_count': 0, 'timeline': []}
    }

    equipment_index = {}  # name -> equipment object mapping

    for cr in chunk_results:
        elements = cr['result'].get('identified_elements', {})

        # Merge equipment
        for equip in elements.get('equipment', []):
            name = equip['name']

            if name in equipment_index:
                # Merge with existing detection
                existing = equipment_index[name]
                existing['appearances'].extend(equip['appearances'])
                existing['mention_count'] = existing.get('mention_count', 0) + equip.get('mention_count', 0)
            else:
                # New equipment
                equipment_index[name] = equip
                combined['equipment'].append(equip)

        # Merge topics (similar approach)
        # ... (implement similar logic for topics, objects, people)

        # Track max people count
        people_data = elements.get('people', {})
        combined['people']['max_count'] = max(
            combined['people']['max_count'],
            people_data.get('max_count', 0)
        )

    # Sort equipment by total visible duration (most prominent first)
    combined['equipment'].sort(
        key=lambda e: sum(
            parse_duration(app['end']) - parse_duration(app['start'])
            for app in e['appearances']
        ),
        reverse=True
    )

    return combined


def extract_context_for_next_chunk(result: dict, chunk: dict) -> str:
    """
    Extract a brief context summary to pass to the next chunk.
    Helps maintain narrative continuity.
    """

    summary = result.get('summary', '')

    # Get last chapter's summary if available
    chapters = result.get('chapters', [])
    last_chapter = chapters[-1] if chapters else None

    context = f"""
Previous chunk ended at {chunk['core_end']//60}:{chunk['core_end']%60:02d}.

Summary: {summary[:300]}...

"""

    if last_chapter:
        context += f"Last chapter: {last_chapter.get('title', 'Unknown')} - {last_chapter.get('summary', '')}"

    return context


def extract_video_segment(video_path: str, start_time: int, end_time: int, output_key: str) -> str:
    """
    Extract a segment from a video using FFmpeg and upload to S3.

    Args:
        video_path: S3 URI of source video
        start_time: Start time in seconds
        end_time: End time in seconds
        output_key: S3 key for output chunk

    Returns:
        str: S3 URI of extracted chunk
    """

    import subprocess
    import tempfile

    # Download source video from S3
    s3 = boto3.client('s3')
    bucket, key = parse_s3_uri(video_path)

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_input:
        s3.download_file(bucket, key, temp_input.name)
        input_path = temp_input.name

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_output:
        output_path = temp_output.name

    # Use FFmpeg to extract segment
    duration = end_time - start_time

    cmd = [
        'ffmpeg',
        '-i', input_path,
        '-ss', str(start_time),  # Start time
        '-t', str(duration),     # Duration
        '-c:v', 'libx264',       # Video codec
        '-c:a', 'aac',           # Audio codec
        '-y',                    # Overwrite output
        output_path
    ]

    subprocess.run(cmd, check=True, capture_output=True)

    # Upload chunk to S3
    s3.upload_file(output_path, bucket, output_key)

    # Clean up temp files
    os.unlink(input_path)
    os.unlink(output_path)

    return f"s3://{bucket}/{output_key}"
```

**Context Preservation Techniques**:

1. **Carry-Forward Summaries**: Each chunk's prompt includes a condensed summary of previous chunks, maintaining narrative thread

2. **Overlap Analysis**: The 10% overlap ensures that events/chapters spanning boundaries are captured in both chunks, then deduplicated during merging

3. **Global Element Tracking**: Equipment and topics detected in one chunk are tracked globally, with time ranges merged across chunks

4. **Temporal Coherence**: Chapter timestamps are adjusted to absolute video time (not relative to chunk), ensuring correct sequencing

5. **Smart Aggregation**: Final summary uses Nova itself to intelligently merge chunk summaries (not simple concatenation)

---

*End of Part 1 documentation. The plan continues with technical implementation details in the complete document.*

## 4. Technical Implementation Plan

### 4.1 Service Layer (`app/services/nova_service.py`)

**Core Functions and Signatures**:

```python
from typing import List, Dict, Optional, Tuple
import boto3
import json
from datetime import datetime

class NovaService:
    """Service for interacting with Amazon Nova models via Bedrock."""

    def __init__(self, region: str = 'us-east-1'):
        """Initialize Bedrock runtime client."""
        self.bedrock = boto3.client('bedrock-runtime', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
        self.region = region

    def analyze_video(
        self,
        s3_key: str,
        model: str,
        analysis_types: List[str],
        options: Optional[Dict] = None
    ) -> Dict:
        """
        Main entry point for Nova video analysis.
        Automatically handles chunking for long videos.

        Args:
            s3_key: S3 key of video file
            model: 'micro', 'lite', 'pro', or 'premier'
            analysis_types: List like ['summary', 'chapters', 'elements']
            options: Optional dict with summary_depth, language, etc.

        Returns:
            Dict with analysis results and metadata
        """
        pass

    def invoke_nova(
        self,
        model_id: str,
        video_s3_uri: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3
    ) -> Dict:
        """
        Low-level function to invoke Nova model.
        Handles API calls, retries, and error handling.

        Args:
            model_id: Full model ID (e.g., 'us.amazon.nova-lite-v1:0')
            video_s3_uri: S3 URI of video
            prompt: Analysis prompt
            max_tokens: Maximum output tokens
            temperature: 0.0-1.0, controls randomness

        Returns:
            Dict with 'result' (text), 'usage' (tokens), 'latency' (ms)
        """
        pass

    def chunk_video(
        self,
        s3_key: str,
        video_duration: int,
        model: str
    ) -> List[Dict]:
        """
        Determine chunking strategy for long videos.

        Args:
            s3_key: S3 key of source video
            video_duration: Video length in seconds
            model: Nova model being used

        Returns:
            List of chunk definitions with start/end times
        """
        pass

    def extract_video_segment(
        self,
        s3_key: str,
        start_time: int,
        end_time: int,
        output_key: str
    ) -> str:
        """
        Extract segment from video using FFmpeg and upload to S3.

        Args:
            s3_key: Source video S3 key
            start_time: Start in seconds
            end_time: End in seconds
            output_key: Destination S3 key for chunk

        Returns:
            S3 URI of extracted chunk
        """
        pass

    def aggregate_results(
        self,
        chunk_results: List[Dict],
        analysis_type: str,
        model: str
    ) -> Dict:
        """
        Aggregate results from multiple video chunks.

        Args:
            chunk_results: List of results from each chunk
            analysis_type: 'summary', 'chapters', or 'elements'
            model: Model used (for re-invoking for aggregation)

        Returns:
            Aggregated results
        """
        pass

    def select_model(
        self,
        video_duration: int,
        quality_preference: str = 'balanced'
    ) -> str:
        """
        Recommend optimal Nova model based on video duration and quality needs.

        Args:
            video_duration: Video length in seconds
            quality_preference: 'fast', 'balanced', or 'best'

        Returns:
            Model name: 'micro', 'lite', 'pro', or 'premier'
        """
        if quality_preference == 'fast':
            return 'micro'
        elif quality_preference == 'best':
            return 'premier'
        else:  # balanced
            if video_duration < 600:  # < 10 minutes
                return 'lite'
            elif video_duration < 1800:  # < 30 minutes
                return 'lite'
            elif video_duration < 3600:  # < 1 hour
                return 'pro'
            else:
                return 'premier'

    def build_prompt(
        self,
        analysis_types: List[str],
        options: Dict,
        chunk_context: Optional[Dict] = None
    ) -> str:
        """
        Build optimized prompt for Nova based on analysis type and options.

        Args:
            analysis_types: Requested analyses
            options: User options (depth, language, etc.)
            chunk_context: Context from previous chunk (if applicable)

        Returns:
            Complete prompt string
        """
        pass

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int
    ) -> float:
        """
        Calculate estimated cost for Nova API usage.

        Args:
            model: Model used
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        PRICING = {
            'micro': {'input': 0.000035, 'output': 0.00014},
            'lite': {'input': 0.00006, 'output': 0.00024},
            'pro': {'input': 0.0008, 'output': 0.0032},
            'premier': {'input': 0.002, 'output': 0.008}  # Estimated
        }

        pricing = PRICING[model]
        cost = (input_tokens / 1000 * pricing['input']) + \
               (output_tokens / 1000 * pricing['output'])
        return round(cost, 4)
```

**Error Handling Strategy**:

```python
from botocore.exceptions import ClientError
import time

def invoke_with_retry(self, model_id: str, request_body: dict, max_retries: int = 3) -> dict:
    """Invoke Nova with exponential backoff retry logic."""

    for attempt in range(max_retries):
        try:
            response = self.bedrock.converse(**request_body)
            return response

        except ClientError as e:
            error_code = e.response['Error']['Code']

            if error_code == 'ThrottlingException':
                # Rate limit hit, wait and retry
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Throttled, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            elif error_code == 'ModelNotReadyException':
                # Model loading, wait longer
                wait_time = 10 * (attempt + 1)
                logger.info(f"Model loading, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue

            elif error_code == 'ValidationException':
                # Invalid request, don't retry
                logger.error(f"Validation error: {e}")
                raise ValueError(f"Invalid Nova request: {e}")

            elif error_code == 'AccessDeniedException':
                # Permission issue, don't retry
                logger.error(f"Access denied: {e}")
                raise PermissionError("Missing IAM permissions for Bedrock Nova")

            else:
                # Unknown error
                logger.error(f"Bedrock error: {error_code} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    raise

    raise Exception(f"Failed after {max_retries} retries")
```

### 4.2 Database Schema Updates

**Recommended Approach: Separate `nova_jobs` Table**

This approach maintains clean separation between Rekognition and Nova functionality while allowing easy correlation via foreign keys.

**Migration SQL**:

```sql
-- Create nova_jobs table
CREATE TABLE IF NOT EXISTS nova_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,  -- FK to jobs table (for correlation)

    -- Nova-specific configuration
    model VARCHAR(20) NOT NULL,  -- 'micro', 'lite', 'pro', 'premier'
    analysis_types TEXT NOT NULL,  -- JSON array: ["summary", "chapters", "elements"]
    user_options TEXT,  -- JSON object with user preferences

    -- Chunking metadata
    is_chunked BOOLEAN DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    chunk_duration INTEGER,  -- Chunk size in seconds (if chunked)
    overlap_duration INTEGER,  -- Overlap in seconds (if chunked)

    -- Results (stored as JSON)
    summary_result TEXT,  -- JSON object with summary
    chapters_result TEXT,  -- JSON array of chapters
    elements_result TEXT,  -- JSON object with equipment/objects/topics

    -- Performance metrics
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_total INTEGER,
    processing_time_seconds FLOAT,
    cost_usd FLOAT,

    -- Status tracking
    status VARCHAR(20) DEFAULT 'SUBMITTED',  -- SUBMITTED, IN_PROGRESS, COMPLETED, FAILED
    error_message TEXT,
    progress_percent INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Foreign key
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX idx_nova_jobs_job_id ON nova_jobs(job_id);
CREATE INDEX idx_nova_jobs_status ON nova_jobs(status);
CREATE INDEX idx_nova_jobs_model ON nova_jobs(model);
CREATE INDEX idx_nova_jobs_created_at ON nova_jobs(created_at DESC);

-- Add service column to existing jobs table (optional, for quick filtering)
ALTER TABLE jobs ADD COLUMN services_used TEXT DEFAULT 'rekognition';
-- Values: 'rekognition', 'nova', 'rekognition,nova'
```

**Field Specifications**:

| Field | Type | Purpose | Nullable | Index |
|-------|------|---------|----------|-------|
| `id` | INTEGER | Primary key | No | Yes (PK) |
| `job_id` | INTEGER | Link to main jobs table | No | Yes |
| `model` | VARCHAR(20) | Nova model used | No | Yes |
| `analysis_types` | TEXT (JSON) | Requested analysis types | No | No |
| `user_options` | TEXT (JSON) | User preferences (depth, language) | Yes | No |
| `is_chunked` | BOOLEAN | Whether video was chunked | No | No |
| `chunk_count` | INTEGER | Number of chunks processed | No | No |
| `summary_result` | TEXT (JSON) | Summary analysis result | Yes | No |
| `chapters_result` | TEXT (JSON) | Chapters analysis result | Yes | No |
| `elements_result` | TEXT (JSON) | Elements analysis result | Yes | No |
| `tokens_total` | INTEGER | Total tokens consumed | Yes | No |
| `cost_usd` | FLOAT | Estimated cost in USD | Yes | No |
| `status` | VARCHAR(20) | Job status | No | Yes |
| `created_at` | TIMESTAMP | Job creation time | No | Yes |

**Database Functions** (`app/database.py` additions):

```python
def create_nova_job(job_id: int, model: str, analysis_types: list, user_options: dict = None) -> int:
    """Create a new Nova analysis job."""
    conn = get_db_connection()
    cursor = conn.execute("""
        INSERT INTO nova_jobs (job_id, model, analysis_types, user_options, status)
        VALUES (?, ?, ?, ?, 'SUBMITTED')
    """, (job_id, model, json.dumps(analysis_types), json.dumps(user_options or {})))
    nova_job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return nova_job_id

def update_nova_job_status(nova_job_id: int, status: str, progress: int = None):
    """Update Nova job status and progress."""
    conn = get_db_connection()
    if progress is not None:
        conn.execute("""
            UPDATE nova_jobs
            SET status = ?, progress_percent = ?
            WHERE id = ?
        """, (status, progress, nova_job_id))
    else:
        conn.execute("""
            UPDATE nova_jobs
            SET status = ?
            WHERE id = ?
        """, (status, nova_job_id))
    conn.commit()
    conn.close()

def save_nova_results(nova_job_id: int, results: dict, metrics: dict):
    """Save Nova analysis results and performance metrics."""
    conn = get_db_connection()
    conn.execute("""
        UPDATE nova_jobs
        SET summary_result = ?,
            chapters_result = ?,
            elements_result = ?,
            tokens_input = ?,
            tokens_output = ?,
            tokens_total = ?,
            processing_time_seconds = ?,
            cost_usd = ?,
            status = 'COMPLETED',
            completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        json.dumps(results.get('summary')),
        json.dumps(results.get('chapters')),
        json.dumps(results.get('elements')),
        metrics['tokens_input'],
        metrics['tokens_output'],
        metrics['tokens_total'],
        metrics['processing_time'],
        metrics['cost'],
        nova_job_id
    ))
    conn.commit()
    conn.close()

def get_nova_job(nova_job_id: int) -> dict:
    """Retrieve Nova job with all details."""
    conn = get_db_connection()
    row = conn.execute("""
        SELECT * FROM nova_jobs WHERE id = ?
    """, (nova_job_id,)).fetchone()
    conn.close()

    if row:
        return dict(row)
    return None
```

**Migration Notes**:
1. Run migration SQL script during deployment
2. Existing `jobs` table remains unchanged (backwards compatible)
3. Nova jobs are optional additions linked via foreign key
4. Can query both tables with JOIN for combined results
5. Deletion of main job cascades to delete Nova job (ON DELETE CASCADE)

### 4.3 API Endpoints (`app/routes/nova_analysis.py`)

**New Blueprint Registration**:

```python
# In app/__init__.py
from app.routes import nova_analysis

app.register_blueprint(nova_analysis.nova_bp, url_prefix='/nova')
```

**Endpoint Definitions**:

**1. Start Nova Analysis**

```python
from flask import Blueprint, request, jsonify
from app.services.nova_service import NovaService
from app.database import create_nova_job, get_job_by_id
import threading

nova_bp = Blueprint('nova', __name__)
nova_service = NovaService()

@nova_bp.route('/analyze', methods=['POST'])
def analyze_video():
    """
    Start Nova video analysis.

    Request JSON:
    {
        "s3_key": "videos/example.mp4",
        "model": "lite",  // 'micro', 'lite', 'pro', 'premier', or 'auto'
        "analysis_types": ["summary", "chapters", "elements"],
        "options": {
            "summary_depth": "standard",  // 'brief', 'standard', 'detailed'
            "language": "auto",  // or 'en', 'es', 'fr', etc.
            "detect_equipment": true,
            "detect_topics": true
        }
    }

    Response JSON:
    {
        "success": true,
        "job_id": 123,
        "nova_job_id": 45,
        "status": "SUBMITTED",
        "model": "lite",
        "estimated_duration": "5-7 minutes",
        "message": "Nova analysis started"
    }
    """
    try:
        data = request.get_json()

        # Validate required fields
        s3_key = data.get('s3_key')
        model = data.get('model', 'auto')
        analysis_types = data.get('analysis_types', ['summary'])
        options = data.get('options', {})

        if not s3_key:
            return jsonify({'success': False, 'error': 'Missing s3_key'}), 400

        # Get existing job or create new one
        job = get_job_by_s3_key(s3_key)
        if not job:
            return jsonify({'success': False, 'error': 'Job not found for this video'}), 404

        job_id = job['id']

        # Auto-select model if requested
        if model == 'auto':
            video_duration = get_video_duration(s3_key)
            model = nova_service.select_model(video_duration, options.get('quality', 'balanced'))

        # Create Nova job record
        nova_job_id = create_nova_job(job_id, model, analysis_types, options)

        # Start async processing in background thread
        thread = threading.Thread(
            target=process_nova_analysis,
            args=(nova_job_id, s3_key, model, analysis_types, options)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'nova_job_id': nova_job_id,
            'status': 'SUBMITTED',
            'model': model,
            'estimated_duration': estimate_duration(model, get_video_duration(s3_key)),
            'message': 'Nova analysis started'
        }), 202

    except Exception as e:
        logger.error(f"Error starting Nova analysis: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def process_nova_analysis(nova_job_id, s3_key, model, analysis_types, options):
    """Background worker function for Nova analysis."""
    try:
        update_nova_job_status(nova_job_id, 'IN_PROGRESS', progress=0)

        # Perform analysis
        results = nova_service.analyze_video(s3_key, model, analysis_types, options)

        # Extract metrics
        metrics = {
            'tokens_input': results['metadata']['tokens_input'],
            'tokens_output': results['metadata']['tokens_output'],
            'tokens_total': results['metadata']['tokens_total'],
            'processing_time': results['metadata']['processing_time'],
            'cost': results['metadata']['cost']
        }

        # Save results
        save_nova_results(nova_job_id, results, metrics)

        logger.info(f"Nova job {nova_job_id} completed successfully")

    except Exception as e:
        logger.error(f"Nova job {nova_job_id} failed: {e}")
        mark_nova_job_failed(nova_job_id, str(e))
```

**2. Check Job Status**

```python
@nova_bp.route('/job-status/<int:nova_job_id>', methods=['GET'])
def get_job_status(nova_job_id):
    """
    Get Nova job status and progress.

    Response JSON:
    {
        "success": true,
        "nova_job_id": 45,
        "job_id": 123,
        "status": "IN_PROGRESS",
        "progress": {
            "percent": 67,
            "chunks_completed": 2,
            "chunks_total": 3,
            "current_stage": "Processing chunk 3/3"
        },
        "model": "lite",
        "created_at": "2025-12-18T10:30:00Z",
        "estimated_completion": "2025-12-18T10:37:00Z"
    }
    """
    try:
        nova_job = get_nova_job(nova_job_id)

        if not nova_job:
            return jsonify({'success': False, 'error': 'Nova job not found'}), 404

        response = {
            'success': True,
            'nova_job_id': nova_job_id,
            'job_id': nova_job['job_id'],
            'status': nova_job['status'],
            'model': nova_job['model'],
            'created_at': nova_job['created_at']
        }

        # Add progress details if in progress
        if nova_job['status'] == 'IN_PROGRESS':
            response['progress'] = {
                'percent': nova_job['progress_percent'],
                'chunks_completed': nova_job.get('chunks_completed', 0),
                'chunks_total': nova_job['chunk_count'],
                'current_stage': f"Processing chunk {nova_job.get('chunks_completed', 0) + 1}/{nova_job['chunk_count']}"
            }

        # Add error if failed
        if nova_job['status'] == 'FAILED':
            response['error'] = nova_job['error_message']

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error getting Nova job status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
```

**3. Get Results**

```python
@nova_bp.route('/results/<int:nova_job_id>', methods=['GET'])
def get_results(nova_job_id):
    """
    Retrieve Nova analysis results.

    Response JSON:
    {
        "success": true,
        "nova_job_id": 45,
        "model": "lite",
        "summary": {...},
        "chapters": [...],
        "identified_elements": {...},
        "metadata": {
            "tokens_used": 15000,
            "processing_time": 342.5,
            "cost_estimate": 0.045,
            "chunk_count": 3
        }
    }
    """
    try:
        nova_job = get_nova_job(nova_job_id)

        if not nova_job:
            return jsonify({'success': False, 'error': 'Nova job not found'}), 404

        if nova_job['status'] != 'COMPLETED':
            return jsonify({
                'success': False,
                'error': f"Job not completed (status: {nova_job['status']})"
            }), 400

        # Parse JSON results
        response = {
            'success': True,
            'nova_job_id': nova_job_id,
            'model': nova_job['model'],
            'summary': json.loads(nova_job['summary_result']) if nova_job['summary_result'] else None,
            'chapters': json.loads(nova_job['chapters_result']) if nova_job['chapters_result'] else None,
            'identified_elements': json.loads(nova_job['elements_result']) if nova_job['elements_result'] else None,
            'metadata': {
                'tokens_used': nova_job['tokens_total'],
                'processing_time': nova_job['processing_time_seconds'],
                'cost_estimate': nova_job['cost_usd'],
                'chunk_count': nova_job['chunk_count']
            }
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error retrieving Nova results: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
```

**4. Combined Analysis Endpoint**

```python
@nova_bp.route('/combined-analysis', methods=['POST'])
def combined_analysis():
    """
    Start both Rekognition and Nova analysis for same video.

    Request JSON:
    {
        "s3_key": "videos/example.mp4",
        "rekognition_types": ["LABELS", "FACES"],
        "nova_model": "lite",
        "nova_analysis_types": ["summary", "chapters"]
    }

    Response JSON:
    {
        "success": true,
        "job_id": 123,
        "rekognition_started": true,
        "nova_job_id": 45,
        "message": "Combined analysis started"
    }
    """
    # Implementation would start both Rekognition and Nova jobs
    pass
```

### 4.4 UI/UX Integration

**Updated `video_analysis.html`** (add Nova options section):

```html
<!-- After Rekognition analysis options -->

<div class="card mt-4">
    <div class="card-header bg-primary text-white">
        <h5><i class="bi bi-stars"></i> AI-Powered Analysis (AWS Nova)</h5>
    </div>
    <div class="card-body">
        <div class="form-check form-switch">
            <input class="form-check-input" type="checkbox" id="enableNova">
            <label class="form-check-label" for="enableNova">
                <strong>Enable Nova AI Analysis</strong>
                <small class="text-muted d-block">Intelligent video summaries, chapters, and semantic understanding</small>
            </label>
        </div>

        <div id="novaOptions" class="mt-3" style="display: none;">
            <!-- Model Selection -->
            <div class="mb-3">
                <label class="form-label">Model Quality <i class="bi bi-info-circle" data-bs-toggle="tooltip" title="Higher quality = slower & more expensive"></i></label>
                <select id="novaModel" class="form-select">
                    <option value="auto" selected>Auto (Recommended)</option>
                    <option value="micro">Micro - Fastest, lowest cost</option>
                    <option value="lite">Lite - Balanced quality and speed</option>
                    <option value="pro">Pro - Highest quality</option>
                    <option value="premier">Premier - Enterprise grade</option>
                </select>
                <small class="form-text text-muted">Auto selects best model based on video duration</small>
            </div>

            <!-- Analysis Types -->
            <div class="mb-3">
                <label class="form-label">Analysis Types</label>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="novaSummary" checked>
                    <label class="form-check-label" for="novaSummary">
                        Video Summary
                    </label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="novaChapters" checked>
                    <label class="form-check-label" for="novaChapters">
                        Chapter Detection
                    </label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="novaElements">
                    <label class="form-check-label" for="novaElements">
                        Identify Equipment & Topics
                    </label>
                </div>
            </div>

            <!-- Summary Options -->
            <div id="summaryOptions" class="mb-3">
                <label class="form-label">Summary Detail Level</label>
                <select id="summaryDepth" class="form-select">
                    <option value="brief">Brief (2-3 sentences)</option>
                    <option value="standard" selected>Standard (1-2 paragraphs)</option>
                    <option value="detailed">Detailed (3-5 paragraphs)</option>
                </select>
            </div>

            <!-- Cost Estimate -->
            <div class="alert alert-info">
                <i class="bi bi-cash"></i> Estimated cost: <span id="novaCostEstimate">$0.02 - $0.10</span>
                <small class="d-block">Actual cost depends on video length and model selected</small>
            </div>
        </div>
    </div>
</div>

<script>
// Show/hide Nova options
document.getElementById('enableNova').addEventListener('change', function(e) {
    document.getElementById('novaOptions').style.display = e.target.checked ? 'block' : 'none';
});

// Update cost estimate when model changes
document.getElementById('novaModel').addEventListener('change', updateCostEstimate);

function updateCostEstimate() {
    const model = document.getElementById('novaModel').value;
    const costRanges = {
        'micro': '$0.01 - $0.05',
        'lite': '$0.02 - $0.10',
        'pro': '$0.20 - $0.80',
        'premier': '$0.50 - $2.00',
        'auto': '$0.02 - $0.10'
    };
    document.getElementById('novaCostEstimate').textContent = costRanges[model] || '$0.02 - $0.10';
}
</script>
```

**Updated `dashboard.html`** (add Nova visualization cards):

```html
<!-- Nova Summary Card -->
<div class="row" id="novaResults" style="display: none;">
    <div class="col-12">
        <div class="card mb-4 border-primary">
            <div class="card-header bg-primary text-white">
                <h5><i class="bi bi-stars"></i> AI Summary (Amazon Nova)</h5>
                <small>Model: <span id="novaModelUsed"></span> | Tokens: <span id="novaTokens"></span> | Cost: $<span id="novaCost"></span></small>
            </div>
            <div class="card-body">
                <p id="novaSummaryText" class="lead"></p>

                <div class="mt-3">
                    <h6>Key Topics:</h6>
                    <div id="novaTopics" class="d-flex flex-wrap gap-2"></div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Nova Chapters Timeline -->
<div class="row" id="novaChaptersSection" style="display: none;">
    <div class="col-12">
        <div class="card mb-4 border-success">
            <div class="card-header bg-success text-white">
                <h5><i class="bi bi-collection-play"></i> Video Chapters</h5>
            </div>
            <div class="card-body">
                <!-- Timeline visualization -->
                <div class="chapters-timeline mb-4" id="chaptersTimeline"></div>

                <!-- Chapter list -->
                <div class="accordion" id="chaptersAccordion"></div>
            </div>
        </div>
    </div>
</div>

<!-- Identified Elements -->
<div class="row" id="novaElementsSection" style="display: none;">
    <div class="col-12">
        <div class="card mb-4 border-warning">
            <div class="card-header bg-warning">
                <h5><i class="bi bi-gear-fill"></i> Identified Elements</h5>
            </div>
            <div class="card-body">
                <ul class="nav nav-tabs mb-3" role="tablist">
                    <li class="nav-item">
                        <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#equipmentTab">
                            Equipment & Tools
                        </button>
                    </li>
                    <li class="nav-item">
                        <button class="nav-link" data-bs-toggle="tab" data-bs-target="#topicsTab">
                            Topics Discussed
                        </button>
                    </li>
                    <li class="nav-item">
                        <button class="nav-link" data-bs-toggle="tab" data-bs-target="#peopleTab">
                            People & Speakers
                        </button>
                    </li>
                </ul>

                <div class="tab-content">
                    <div id="equipmentTab" class="tab-pane active">
                        <table class="table table-hover" id="equipmentTable">
                            <thead>
                                <tr>
                                    <th>Equipment</th>
                                    <th>Category</th>
                                    <th>Time Visible</th>
                                    <th>Discussed</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>
                    <div id="topicsTab" class="tab-pane">
                        <table class="table table-hover" id="topicsTable">
                            <thead>
                                <tr>
                                    <th>Topic</th>
                                    <th>Mentions</th>
                                    <th>Time Ranges</th>
                                    <th>Importance</th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>
                    <div id="peopleTab" class="tab-pane">
                        <div id="peopleInfo"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<script src="/static/js/nova-dashboard.js"></script>
```

**New JavaScript file: `app/static/js/nova-dashboard.js`**:

```javascript
function loadNovaResults(jobId) {
    fetch(`/nova/results/${jobId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                displayNovaResults(data);
            }
        })
        .catch(error => console.error('Error loading Nova results:', error));
}

function displayNovaResults(data) {
    // Display summary
    if (data.summary) {
        document.getElementById('novaResults').style.display = 'block';
        document.getElementById('novaSummaryText').textContent = data.summary.text;
        document.getElementById('novaModelUsed').textContent = data.model.toUpperCase();
        document.getElementById('novaTokens').textContent = data.metadata.tokens_used.toLocaleString();
        document.getElementById('novaCost').textContent = data.metadata.cost_estimate.toFixed(4);

        // Display key topics as badges
        const topicsDiv = document.getElementById('novaTopics');
        topicsDiv.innerHTML = '';
        (data.summary.key_topics || []).forEach(topic => {
            topicsDiv.innerHTML += `<span class="badge bg-primary">${topic}</span>`;
        });
    }

    // Display chapters
    if (data.chapters && data.chapters.length > 0) {
        document.getElementById('novaChaptersSection').style.display = 'block';
        displayChapters(data.chapters);
    }

    // Display identified elements
    if (data.identified_elements) {
        document.getElementById('novaElementsSection').style.display = 'block';
        displayElements(data.identified_elements);
    }
}

function displayChapters(chapters) {
    const timeline = document.getElementById('chaptersTimeline');
    const accordion = document.getElementById('chaptersAccordion');

    accordion.innerHTML = '';

    chapters.forEach((chapter, index) => {
        // Add to accordion
        accordion.innerHTML += `
            <div class="accordion-item">
                <h2 class="accordion-header">
                    <button class="accordion-button ${index > 0 ? 'collapsed' : ''}"
                            type="button"
                            data-bs-toggle="collapse"
                            data-bs-target="#chapter${index}">
                        ${chapter.index}. ${chapter.title}
                        <span class="ms-auto me-3 text-muted">${chapter.start_time} - ${chapter.end_time}</span>
                    </button>
                </h2>
                <div id="chapter${index}" class="accordion-collapse collapse ${index === 0 ? 'show' : ''}">
                    <div class="accordion-body">
                        <p><strong>Summary:</strong> ${chapter.summary}</p>
                        ${chapter.key_points ? `
                            <p><strong>Key Points:</strong></p>
                            <ul>
                                ${chapter.key_points.map(p => `<li>${p}</li>`).join('')}
                            </ul>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    });
}

function displayElements(elements) {
    // Display equipment
    const equipmentTable = document.getElementById('equipmentTable').querySelector('tbody');
    equipmentTable.innerHTML = '';

    (elements.equipment || []).forEach(equip => {
        const totalDuration = equip.appearances.reduce((sum, app) =>
            sum + (parseTime(app.end) - parseTime(app.start)), 0);

        equipmentTable.innerHTML += `
            <tr>
                <td><strong>${equip.name}</strong></td>
                <td><span class="badge bg-secondary">${equip.category}</span></td>
                <td>${formatDuration(totalDuration)}</td>
                <td>${equip.discussed ? '<i class="bi bi-check-circle-fill text-success"></i>' : '-'}</td>
            </tr>
        `;
    });

    // Display topics
    const topicsTable = document.getElementById('topicsTable').querySelector('tbody');
    topicsTable.innerHTML = '';

    (elements.topics_discussed || []).forEach(topic => {
        const importance = topic.importance || 'medium';
        const badgeClass = importance === 'high' ? 'bg-danger' : importance === 'medium' ? 'bg-warning' : 'bg-info';

        topicsTable.innerHTML += `
            <tr>
                <td><strong>${topic.topic}</strong></td>
                <td>${topic.mentions}</td>
                <td>${topic.time_ranges.map(r => r.join(' - ')).join(', ')}</td>
                <td><span class="badge ${badgeClass}">${importance.toUpperCase()}</span></td>
            </tr>
        `;
    });
}

function parseTime(timeStr) {
    const [min, sec] = timeStr.split(':').map(Number);
    return min * 60 + sec;
}

function formatDuration(seconds) {
    const min = Math.floor(seconds / 60);
    const sec = seconds % 60;
    return `${min}:${sec.toString().padStart(2, '0')}`;
}
```

### 4.5 Export Format Updates

**Excel Export with Nova Data**:

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

def export_nova_to_excel(nova_job_id, output_path):
    """Export Nova results to Excel with multiple sheets."""

    nova_job = get_nova_job(nova_job_id)
    wb = Workbook()

    # Remove default sheet
    wb.remove(wb.active)

    # Sheet 1: Nova Summary
    ws_summary = wb.create_sheet("Nova Summary")
    ws_summary.append(["Field", "Value"])
    ws_summary.append(["Model Used", nova_job['model'].upper()])

    if nova_job['summary_result']:
        summary = json.loads(nova_job['summary_result'])
        ws_summary.append(["Summary Text", summary['text']])
        ws_summary.append(["Word Count", summary['word_count']])
        ws_summary.append(["Language", summary['language']])
        ws_summary.append(["Key Topics", ", ".join(summary.get('key_topics', []))])

    ws_summary.append([""])
    ws_summary.append(["Performance Metrics", ""])
    ws_summary.append(["Tokens Used", nova_job['tokens_total']])
    ws_summary.append(["Processing Time", f"{nova_job['processing_time_seconds']:.2f} seconds"])
    ws_summary.append(["Estimated Cost", f"${nova_job['cost_usd']:.4f}"])

    # Format header row
    for cell in ws_summary[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        cell.font = Font(color="FFFFFF", bold=True)

    # Sheet 2: Chapters
    if nova_job['chapters_result']:
        ws_chapters = wb.create_sheet("Chapters")
        ws_chapters.append(["#", "Title", "Start Time", "End Time", "Duration", "Summary", "Key Points"])

        chapters = json.loads(nova_job['chapters_result'])
        for chapter in chapters:
            ws_chapters.append([
                chapter['index'],
                chapter['title'],
                chapter['start_time'],
                chapter['end_time'],
                chapter.get('duration', ''),
                chapter['summary'],
                "; ".join(chapter.get('key_points', []))
            ])

        # Format header
        for cell in ws_chapters[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")
            cell.font = Font(color="FFFFFF", bold=True)

    # Sheet 3: Identified Elements
    if nova_job['elements_result']:
        ws_elements = wb.create_sheet("Identified Elements")
        ws_elements.append(["Type", "Name", "Category", "Time Visible", "Discussed", "Mentions"])

        elements = json.loads(nova_job['elements_result'])

        # Add equipment
        for equip in elements.get('equipment', []):
            time_ranges = ", ".join([f"{app['start']}-{app['end']}" for app in equip['appearances']])
            ws_elements.append([
                "Equipment",
                equip['name'],
                equip['category'],
                time_ranges,
                "Yes" if equip.get('discussed') else "No",
                equip.get('mention_count', 0)
            ])

        # Add topics
        for topic in elements.get('topics_discussed', []):
            time_ranges = ", ".join([f"{r[0]}-{r[1]}" for r in topic['time_ranges']])
            ws_elements.append([
                "Topic",
                topic['topic'],
                topic.get('importance', 'medium'),
                time_ranges,
                "Yes",
                topic['mentions']
            ])

        # Format header
        for cell in ws_elements[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")

    # Auto-size columns
    for ws in wb.worksheets:
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[column_letter].width = min(max_length + 2, 50)

    wb.save(output_path)
    return output_path
```

**JSON Export Schema**:

```json
{
  "job_id": 123,
  "video_metadata": {
    "s3_key": "videos/example.mp4",
    "duration": 1825,
    "file_size": 450000000
  },
  "rekognition_results": {
    "labels": [...],
    "faces": [...]
  },
  "nova_results": {
    "nova_job_id": 45,
    "model": "lite",
    "analysis_types": ["summary", "chapters", "elements"],
    "summary": {
      "text": "...",
      "depth": "standard",
      "language": "en",
      "word_count": 156,
      "key_topics": ["topic1", "topic2"]
    },
    "chapters": [
      {
        "index": 1,
        "title": "Introduction",
        "start_time": "00:00",
        "end_time": "03:00",
        "summary": "...",
        "key_points": ["..."]
      }
    ],
    "identified_elements": {
      "equipment": [...],
      "topics_discussed": [...]
    },
    "metadata": {
      "tokens_used": 15234,
      "processing_time": 342.5,
      "cost_estimate": 0.045,
      "chunk_count": 0
    }
  }
}
```

## 5. Cost & Performance Considerations

### 5.1 Cost Estimates

**Pricing Summary** (Based on AWS Bedrock Nova pricing as of December 2024):

| Model | Input (per 1K tokens) | Output (per 1K tokens) | Total per Typical Analysis* |
|-------|----------------------|------------------------|----------------------------|
| **Nova Micro** | $0.035 | $0.14 | $0.01 - $0.05 |
| **Nova Lite** | $0.06 | $0.24 | $0.02 - $0.10 |
| **Nova Pro** | $0.80 | $3.20 | $0.20 - $0.80 |
| **Nova Premier** | ~$2.00 | ~$8.00 | $0.50 - $2.00 |

*Typical analysis: 5-30 minute video with summary + chapters

**Per-Video Cost Estimates**:

| Video Length | Model | Est. Input Tokens | Est. Output Tokens | Estimated Cost |
|--------------|-------|-------------------|--------------------|----------------|
| 5 minutes | Micro | ~5,000 | ~500 | $0.01 - $0.02 |
| 5 minutes | Lite | ~5,000 | ~500 | $0.02 - $0.03 |
| 5 minutes | Pro | ~5,000 | ~500 | $0.05 - $0.06 |
| 15 minutes | Lite | ~15,000 | ~1,000 | $0.05 - $0.08 |
| 15 minutes | Pro | ~15,000 | ~1,000 | $0.15 - $0.20 |
| 30 minutes | Lite | ~28,000 | ~2,000 | $0.08 - $0.12 |
| 30 minutes | Pro | ~28,000 | ~2,000 | $0.25 - $0.35 |
| 60 minutes (2 chunks) | Lite | ~56,000 | ~3,000 | $0.15 - $0.25 |
| 60 minutes (2 chunks) | Pro | ~56,000 | ~3,000 | $0.50 - $0.70 |
| 2 hours (5 chunks) | Pro | ~140,000 | ~5,000 | $1.00 - $1.50 |
| 2 hours (3 chunks) | Premier | ~120,000 | ~4,000 | $2.00 - $3.00 |

**Model Cost Trade-offs**:

**When to recommend Micro**:
- High-volume batch processing (100+ videos)
- Cost is primary constraint (budget < $0.05/video)
- Quick preview/categorization needed
- Videos are short (< 10 minutes)
- Quality can be "good enough" rather than excellent

**When to recommend Lite** (Default):
- General-purpose use cases
- Balanced budget ($0.05-$0.20/video acceptable)
- Videos 5-30 minutes
- Good quality needed but not mission-critical
- Most tutorial, presentation, and webinar content

**When to recommend Pro**:
- Complex content requiring deep understanding
- Multi-speaker conversations or interviews
- Technical or specialized subject matter
- Budget allows $0.20-$1.00/video
- Accuracy is important
- Legal, medical, or educational content

**When to recommend Premier**:
- Mission-critical applications
- Very long videos (> 1 hour)
- Maximum accuracy required
- Enterprise/compliance use cases
- Budget > $1.00/video acceptable
- Full conference sessions or documentaries

**Cost Optimization Tips**:

1. **Use auto model selection**: Let system choose based on duration and needs
2. **Cache results**: Store summaries to avoid reprocessing same video
3. **Selective analysis**: Only request needed features (skip elements if not needed)
4. **Batch similar videos**: Process during off-peak if possible
5. **Start with Micro**: Use for preview, upgrade to Pro only if needed
6. **Limit chunk count**: Overlap adds cost—use minimum necessary (10%)
7. **Set budget alerts**: Configure AWS Budgets to monitor Bedrock spend
8. **Use S3 URI**: Avoids payload size issues and reduces data transfer
9. **Compress videos**: Lower bitrate videos use fewer tokens (same content)
10. **Summary depth control**: Brief summaries cost less than detailed

### 5.2 Performance Expectations

**Processing Times** (Estimated based on AWS Bedrock latency):

| Video Length | Model | Processing Time | Realtime Factor | User Wait Time |
|--------------|-------|----------------|-----------------|----------------|
| 5 minutes | Micro | ~30-60s | 0.1-0.2x | < 1 minute |
| 5 minutes | Lite | ~45-90s | 0.15-0.3x | 1-2 minutes |
| 5 minutes | Pro | ~60-120s | 0.2-0.4x | 1-2 minutes |
| 15 minutes | Lite | ~90-180s | 0.1-0.2x | 2-3 minutes |
| 15 minutes | Pro | ~120-240s | 0.13-0.27x | 2-4 minutes |
| 30 minutes | Lite | ~180-300s | 0.1-0.17x | 3-5 minutes |
| 30 minutes | Pro | ~240-420s | 0.13-0.23x | 4-7 minutes |
| 60 minutes (chunked) | Lite | ~300-600s | 0.08-0.17x | 5-10 minutes |
| 60 minutes (chunked) | Pro | ~480-840s | 0.13-0.23x | 8-14 minutes |
| 2 hours (chunked) | Pro | ~900-1800s | 0.125-0.25x | 15-30 minutes |

*Realtime factor: Processing time / Video duration (lower is faster)*

**Async Processing Model**:

Nova analysis follows same async pattern as Rekognition:
1. **Submit job**: Returns immediately with job ID
2. **Poll status**: Check every 10-15 seconds for completion
3. **Retrieve results**: Fetch when status = COMPLETED
4. **Auto-refresh UI**: History page polls running jobs automatically

**User Expectation Management**:

Display estimates in UI:
- **Short videos (< 5 min)**: "Results in 1-2 minutes"
- **Medium videos (5-30 min)**: "Results in 3-7 minutes"
- **Long videos (> 30 min)**: "Results in 10-30 minutes depending on length"

Show progress indicators:
- Chunk completion: "Processing chunk 2 of 5 (40%)"
- Stage updates: "Analyzing video...", "Generating chapters...", "Aggregating results..."
- Time remaining estimate: "Estimated 3 minutes remaining"

## 6. Implementation Phases

### Phase 1: Foundation (Core Nova Integration)

**Goal**: Basic Nova integration supporting single-chunk videos

**Tasks**:
1. Set up IAM permissions for Bedrock Nova access
2. Implement `app/services/nova_service.py` with core functions
3. Add `nova_jobs` database table
4. Create `/nova/analyze` and `/nova/results` API endpoints
5. Test with short videos (< 5 minutes)
6. Verify cost tracking and metrics

**Files to Create**:
- `app/services/nova_service.py` - Nova service layer with invoke, prompt building
- `app/routes/nova_analysis.py` - API blueprint for Nova endpoints
- `migrations/001_add_nova_jobs.sql` - Database migration script

**Files to Modify**:
- `app/__init__.py` - Register nova_analysis blueprint
- `app/database.py` - Add nova_jobs CRUD functions (create, update, get)
- `requirements.txt` - Ensure boto3 >= 1.28.57, add any nova-specific deps
- `.env` - Add any Nova-specific environment variables (region, model defaults)

**Success Criteria**:
- Can successfully analyze videos < 5 minutes with Nova Lite
- Results stored correctly in database with all metadata
- Cost calculation accurate (within 10% of actual AWS billing)
- Basic error handling works (permission errors, invalid videos)
- API returns proper status codes and error messages

**Testing**:
- Test with 3-minute tutorial video
- Test with 5-minute presentation
- Test with invalid S3 key (should fail gracefully)
- Test with missing IAM permissions (should return clear error)

### Phase 2: Chunking & Long Video Support

**Goal**: Handle videos of any length via automatic chunking

**Tasks**:
1. Implement video chunking algorithm (from section 3.3)
2. Add FFmpeg integration for video segmentation
3. Build result aggregation logic for summaries and chapters
4. Add chunk progress tracking to database
5. Update status endpoint to show chunk progress
6. Test with 30-minute, 1-hour, and 2-hour videos

**Files to Create**:
- `app/services/video_chunker.py` - Chunking logic and FFmpeg wrapper
- `app/services/nova_aggregator.py` - Result aggregation strategies

**Files to Modify**:
- `app/services/nova_service.py` - Add chunking workflow, multi-chunk processing
- `app/routes/nova_analysis.py` - Update status endpoint with chunk progress
- `app/database.py` - Add chunk tracking fields updates

**Success Criteria**:
- Successfully processes 2-hour video with coherent results
- Aggregated summaries read naturally (not disjointed)
- Chapters don't have duplicates in overlap regions
- Progress tracking shows accurate chunk completion (X/Y chunks done)
- Temporary chunk files cleaned up after processing

**Testing**:
- 30-minute video (2 chunks)
- 90-minute video (4 chunks)
- 2-hour video (5 chunks)
- Verify chapter deduplication in overlap regions
- Verify summary coherence across chunks

### Phase 3: Chapter Detection & Element Identification

**Goal**: Full feature implementation with all analysis types

**Tasks**:
1. Enhance prompt engineering for chapter detection
2. Add equipment and object identification prompts
3. Implement topic extraction logic
4. Add speaker diarization output parsing
5. Test accuracy with diverse video types
6. Iterate on prompts based on results

**Files to Modify**:
- `app/services/nova_service.py` - Add specialized prompts for each analysis type
- `app/database.py` - Ensure proper JSON serialization for complex results

**Success Criteria**:
- Chapter detection produces 5-10 logical chapters for 30-min video
- Equipment identification finds 80%+ of visible tools/devices
- Topic extraction identifies main themes accurately
- Speaker diarization distinguishes between multiple speakers

**Testing**:
- Tutorial video: Verify equipment detection (cameras, computers)
- Interview: Verify speaker diarization (2-3 speakers)
- Presentation: Verify topic extraction aligns with slides
- Product review: Verify brand/product mentions

### Phase 4: UI/UX Integration

**Goal**: Complete user interface integration with Nova features

**Tasks**:
1. Update `video_analysis.html` with Nova options panel
2. Add Nova results visualization to `dashboard.html`
3. Update `history.html` to show Nova job status
4. Implement Excel/JSON export with Nova data
5. Add Nova vs Rekognition comparison view
6. User testing and UI refinement

**Files to Create**:
- `app/static/js/nova-dashboard.js` - Client-side Nova visualization logic

**Files to Modify**:
- `app/templates/video_analysis.html` - Add Nova selection UI
- `app/templates/dashboard.html` - Add Nova result cards and charts
- `app/templates/history.html` - Add Nova status column
- `app/routes/analysis.py` - Add Excel export for combined results
- `app/static/css/style.css` - Nova-specific styling

**Success Criteria**:
- Intuitive checkbox/dropdown UI for Nova options
- Beautiful chapter timeline visualization
- Identified elements displayed in organized tables
- Excel export includes all Nova data with formatting
- Mobile-responsive design works well

**Testing**:
- Test UI on desktop (Chrome, Firefox, Edge)
- Test on tablet and mobile devices
- Verify Excel export opens correctly in Microsoft Excel
- Verify JSON export is valid and complete

### Phase 5: Polish & Optimization

**Goal**: Production-ready implementation with performance optimization

**Tasks**:
1. Implement result caching (avoid reprocessing same video)
2. Add parallel chunk processing option
3. Comprehensive error handling and logging
4. Add CloudWatch metrics and alarms
5. Performance profiling and optimization
6. Security review (IAM, input validation)
7. Documentation (API docs, user guide)

**Files to Modify**:
- All service files - Add caching layer with Redis/DB
- All route files - Enhanced error handling, logging
- `app/services/nova_service.py` - Parallel chunk processing option

**Files to Create**:
- `docs/NOVA_API.md` - API documentation
- `docs/USER_GUIDE_NOVA.md` - User guide with screenshots

**Success Criteria**:
- Average error rate < 2% in production
- 90% of analyses complete within estimated time
- Cost per video matches predictions (±15%)
- Comprehensive logging for troubleshooting
- All edge cases handled gracefully
- Documentation complete and accurate

**Testing**:
- Load testing: 50 concurrent requests
- Stress testing: Process 100 videos in sequence
- Error injection: Simulate API failures, network issues
- Security testing: Try SQL injection, XSS, unauthorized access

---

## 7. Video Proxy Generation & Embeddings Pipeline

### 7.1 Video Proxy Strategy

**Rationale for 720p15 Proxies**:
- **Cost Reduction**: Smaller file size = fewer tokens = lower Nova processing costs
- **Faster Processing**: 15 FPS (vs 30 FPS) reduces frame count by 50% while maintaining adequate sampling
- **Quality Preservation**: 720p provides sufficient resolution for Nova's visual understanding
- **Bandwidth Optimization**: Faster S3 uploads/downloads
- **Consistent Processing**: Normalized format eliminates codec/resolution variability issues

**Proxy Specifications**:
- **Resolution**: 1280x720 (720p)
- **Frame Rate**: 15 FPS
- **Video Codec**: H.264 (libx264)
- **Audio Codec**: AAC
- **Bitrate**: 2 Mbps video, 128 kbps audio
- **Container**: MP4
- **Naming Convention**: `{original_filename}_proxy_720p15.mp4`

### 7.2 Proxy Generation Implementation

**FFmpeg Command Structure**:

```python
def generate_video_proxy(
    input_s3_key: str,
    output_s3_key: str,
    target_resolution: str = '720',
    target_fps: int = 15
) -> str:
    """
    Generate 720p15 proxy video for Nova processing.

    Args:
        input_s3_key: Original video S3 key
        output_s3_key: Proxy video destination S3 key
        target_resolution: Height in pixels (default: 720)
        target_fps: Target frame rate (default: 15)

    Returns:
        S3 URI of generated proxy video
    """
    import subprocess
    import tempfile
    import os

    s3 = boto3.client('s3')
    bucket = 'video-analysis-app-676206912644'

    # Download original video
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_input:
        s3.download_file(bucket, input_s3_key, temp_input.name)
        input_path = temp_input.name

    # Generate proxy
    with tempfile.NamedTemporaryFile(suffix='_proxy.mp4', delete=False) as temp_output:
        output_path = temp_output.name

    # FFmpeg command for proxy generation
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', input_path,
        '-vf', f'scale=-2:{target_resolution}',  # Maintain aspect ratio
        '-r', str(target_fps),                    # Set frame rate
        '-c:v', 'libx264',                        # Video codec
        '-preset', 'medium',                      # Encoding speed/quality balance
        '-crf', '23',                             # Constant quality (18-28 range, 23 = good)
        '-maxrate', '2M',                         # Max bitrate 2 Mbps
        '-bufsize', '4M',                         # Buffer size
        '-c:a', 'aac',                            # Audio codec
        '-b:a', '128k',                           # Audio bitrate
        '-ar', '48000',                           # Audio sample rate
        '-y',                                     # Overwrite output
        output_path
    ]

    # Execute FFmpeg
    try:
        result = subprocess.run(
            ffmpeg_cmd,
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"Proxy generated successfully: {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr}")
        raise Exception(f"Failed to generate proxy: {e.stderr}")

    # Upload proxy to S3
    s3.upload_file(output_path, bucket, output_s3_key)
    logger.info(f"Proxy uploaded to S3: s3://{bucket}/{output_s3_key}")

    # Clean up temp files
    os.unlink(input_path)
    os.unlink(output_path)

    # Get proxy file stats
    proxy_info = s3.head_object(Bucket=bucket, Key=output_s3_key)
    proxy_size_mb = proxy_info['ContentLength'] / (1024 * 1024)

    logger.info(f"Proxy size: {proxy_size_mb:.2f} MB")

    return f"s3://{bucket}/{output_s3_key}"
```

**Proxy Generation Workflow**:

```python
def process_video_with_proxy(original_s3_key: str, job_id: int):
    """
    Complete workflow: Generate proxy → Process with Nova → Store results.
    """
    # Step 1: Generate proxy video
    proxy_s3_key = original_s3_key.replace('.mp4', '_proxy_720p15.mp4')
    proxy_uri = generate_video_proxy(original_s3_key, proxy_s3_key)

    logger.info(f"Processing proxy: {proxy_uri}")

    # Step 2: Process proxy with Nova (not original)
    nova_results = nova_service.analyze_video(
        s3_key=proxy_s3_key,  # Use proxy, not original
        model='lite',
        analysis_types=['summary', 'chapters', 'elements']
    )

    # Step 3: Store proxy reference in database
    update_job_proxy_info(job_id, proxy_s3_key, proxy_uri)

    return nova_results
```

### 7.3 Standardized JSON Output Format

**Complete Segment Analysis Schema**:

```json
{
  "video_metadata": {
    "original_file": "videos/example.mp4",
    "proxy_file": "videos/example_proxy_720p15.mp4",
    "duration_seconds": 1825,
    "original_size_mb": 450.5,
    "proxy_size_mb": 85.2,
    "resolution_original": "1920x1080",
    "resolution_proxy": "1280x720",
    "fps_original": 30,
    "fps_proxy": 15,
    "processed_at": "2025-12-18T15:30:00Z"
  },
  "whisper_transcript": {
    "transcript_id": 123,
    "model": "large-v3",
    "language": "en",
    "duration_seconds": 1825,
    "full_text": "...",
    "segments": [
      {
        "id": 1,
        "start": 0.0,
        "end": 5.5,
        "text": "Welcome to this tutorial on portrait photography.",
        "words": [
          {"word": "Welcome", "start": 0.0, "end": 0.5},
          {"word": "to", "start": 0.5, "end": 0.6}
        ],
        "confidence": 0.95
      }
    ],
    "word_count": 2847,
    "character_count": 15234
  },
  "nova_analysis": {
    "nova_job_id": 45,
    "model": "lite",
    "processed_proxy": true,
    "summary": {
      "text": "This video provides a comprehensive tutorial on portrait photography...",
      "depth": "standard",
      "language": "en",
      "word_count": 156,
      "key_topics": ["portrait photography", "camera settings", "lighting"]
    },
    "chapters": [
      {
        "index": 1,
        "title": "Introduction and Equipment Overview",
        "start_time": "00:00",
        "start_seconds": 0.0,
        "end_time": "03:00",
        "end_seconds": 180.5,
        "duration_seconds": 180.5,
        "summary": "Instructor introduces the tutorial and showcases equipment.",
        "key_points": ["Course overview", "Equipment introduction"],
        "transcript_segment_ids": [1, 2, 3, 4, 5],  // Links to Whisper segments
        "identified_elements": {
          "equipment": ["Canon EOS R5", "50mm f/1.8 lens"],
          "topics": ["photography equipment", "tutorial introduction"]
        }
      }
    ],
    "identified_elements": {
      "equipment": [
        {
          "name": "Canon EOS R5",
          "category": "photography",
          "time_ranges": [{"start": 30, "end": 180}],
          "discussed": true,
          "transcript_mentions": [
            {"segment_id": 2, "text": "this Canon EOS R5 camera"}
          ]
        }
      ],
      "topics_discussed": [
        {
          "topic": "aperture and depth of field",
          "time_ranges": [[120, 270]],
          "mentions": 18,
          "importance": "high",
          "transcript_segments": [8, 9, 10, 11]
        }
      ]
    },
    "tokens_used": 15234,
    "processing_time_seconds": 342.5,
    "cost_usd": 0.045
  },
  "combined_insights": {
    "transcript_nova_alignment": {
      "chapters_with_transcripts": 5,
      "transcript_coverage": 0.98,
      "topics_mentioned_in_both": ["aperture", "lighting", "composition"]
    }
  }
}
```

### 7.4 Database Schema for Combined Storage

**Updated Database Schema** (extends existing tables):

```sql
-- Add proxy and embeddings columns to jobs table
ALTER TABLE jobs ADD COLUMN proxy_s3_key TEXT;
ALTER TABLE jobs ADD COLUMN proxy_size_mb FLOAT;
ALTER TABLE jobs ADD COLUMN proxy_generated_at TIMESTAMP;

-- Link transcripts to jobs
ALTER TABLE transcripts ADD COLUMN job_id INTEGER;
ALTER TABLE transcripts ADD FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE;

-- Create embeddings table
CREATE TABLE IF NOT EXISTS video_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    transcript_id INTEGER,
    nova_job_id INTEGER,

    -- Embedding metadata
    embedding_type VARCHAR(50) NOT NULL,  -- 'full_video', 'chapter', 'segment'
    embedding_model VARCHAR(50) DEFAULT 'amazon.nova-embed-v1',
    embedding_dimension INTEGER DEFAULT 1024,

    -- Reference to source content
    chapter_index INTEGER,  -- NULL for full video embedding
    segment_index INTEGER,  -- NULL for full video/chapter embeddings
    start_time FLOAT,
    end_time FLOAT,

    -- Source text
    source_text TEXT NOT NULL,  -- Combined Whisper + Nova text
    source_type VARCHAR(20),  -- 'transcript', 'nova_summary', 'combined'

    -- Embedding vector (stored as JSON array or BLOB)
    embedding_vector TEXT NOT NULL,  -- JSON array of floats

    -- Metadata
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Foreign keys
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (transcript_id) REFERENCES transcripts(id) ON DELETE SET NULL,
    FOREIGN KEY (nova_job_id) REFERENCES nova_jobs(id) ON DELETE SET NULL
);

-- Indexes for semantic search
CREATE INDEX idx_embeddings_job_id ON video_embeddings(job_id);
CREATE INDEX idx_embeddings_type ON video_embeddings(embedding_type);
CREATE INDEX idx_embeddings_chapter ON video_embeddings(chapter_index);

-- Create embedding batches table (track batch processing)
CREATE TABLE IF NOT EXISTS embedding_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    batch_status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING, PROCESSING, COMPLETED, FAILED
    items_count INTEGER,
    items_processed INTEGER DEFAULT 0,
    batch_input_s3_key TEXT,  -- S3 key for batch input JSONL
    batch_output_s3_key TEXT,  -- S3 key for batch output
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,

    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
```

### 7.5 Amazon Nova Multimodal Embeddings Integration

**Overview of Nova Embeddings**:
- **Model**: `amazon.nova-embed-text-v1` and `amazon.nova-embed-multimodal-v1`
- **Dimension**: 1024-dimensional vectors
- **Input**: Text (up to 8K tokens) or multimodal (text + image)
- **Use Case**: Semantic search, RAG, similarity matching
- **Batch API**: Process multiple items efficiently

**Embeddings Generation Strategy**:

```python
def generate_embeddings_for_video(job_id: int, transcript_id: int, nova_job_id: int):
    """
    Generate embeddings from combined Whisper transcript + Nova analysis.

    Strategy:
    1. Full video embedding (entire transcript + summary)
    2. Chapter-level embeddings (chapter summary + relevant transcript segments)
    3. Segment-level embeddings (individual transcript segments)
    """

    # Retrieve data
    transcript = get_transcript(transcript_id)
    nova_job = get_nova_job(nova_job_id)

    whisper_segments = json.loads(transcript['segments'])
    nova_summary = json.loads(nova_job['summary_result'])
    nova_chapters = json.loads(nova_job['chapters_result'])

    embedding_tasks = []

    # Task 1: Full video embedding
    full_text = f"""
Video Summary: {nova_summary['text']}

Full Transcript:
{transcript['transcript_text']}
"""
    embedding_tasks.append({
        'type': 'full_video',
        'text': full_text[:8000],  # Respect 8K token limit
        'metadata': {
            'job_id': job_id,
            'transcript_id': transcript_id,
            'nova_job_id': nova_job_id,
            'start_time': 0,
            'end_time': transcript['duration_seconds']
        }
    })

    # Task 2: Chapter-level embeddings
    for chapter in nova_chapters:
        # Find transcript segments for this chapter
        chapter_segments = [
            seg for seg in whisper_segments
            if chapter['start_seconds'] <= seg['start'] < chapter['end_seconds']
        ]

        chapter_transcript = " ".join([seg['text'] for seg in chapter_segments])

        chapter_text = f"""
Chapter {chapter['index']}: {chapter['title']}

Summary: {chapter['summary']}

Key Points: {', '.join(chapter.get('key_points', []))}

Transcript:
{chapter_transcript}
"""

        embedding_tasks.append({
            'type': 'chapter',
            'text': chapter_text[:8000],
            'metadata': {
                'job_id': job_id,
                'chapter_index': chapter['index'],
                'start_time': chapter['start_seconds'],
                'end_time': chapter['end_seconds']
            }
        })

    # Task 3: Segment-level embeddings (for fine-grained search)
    for i, segment in enumerate(whisper_segments[::5]):  # Every 5th segment to reduce count
        embedding_tasks.append({
            'type': 'segment',
            'text': segment['text'],
            'metadata': {
                'job_id': job_id,
                'segment_index': i * 5,
                'start_time': segment['start'],
                'end_time': segment['end']
            }
        })

    # Generate embeddings using batch API
    embeddings = generate_embeddings_batch(embedding_tasks)

    # Store in database
    save_embeddings_to_db(embeddings)

    return embeddings
```

**Batch Embeddings API Implementation**:

```python
def generate_embeddings_batch(tasks: List[dict]) -> List[dict]:
    """
    Generate embeddings using Amazon Nova Embeddings Batch API.

    Args:
        tasks: List of embedding tasks with text and metadata

    Returns:
        List of embeddings with vectors
    """
    import json
    import tempfile
    from datetime import datetime

    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    s3 = boto3.client('s3')

    bucket = 'video-analysis-app-676206912644'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Prepare batch input (JSONL format)
    batch_input_lines = []
    for i, task in enumerate(tasks):
        batch_input_lines.append(json.dumps({
            'recordId': f"record_{i}",
            'modelInput': {
                'inputText': task['text'],
                'embeddingTypes': ['text']  # or ['multimodal'] if including images
            }
        }))

    batch_input_jsonl = "\n".join(batch_input_lines)

    # Upload batch input to S3
    input_s3_key = f"embeddings/batch_input_{timestamp}.jsonl"
    s3.put_object(
        Bucket=bucket,
        Key=input_s3_key,
        Body=batch_input_jsonl.encode('utf-8')
    )

    # Submit batch job
    output_s3_key = f"embeddings/batch_output_{timestamp}/"

    response = bedrock.start_batch_inference(
        modelId='amazon.nova-embed-text-v1',
        inputDataConfig={
            's3InputDataConfig': {
                's3Uri': f"s3://{bucket}/{input_s3_key}"
            }
        },
        outputDataConfig={
            's3OutputDataConfig': {
                's3Uri': f"s3://{bucket}/{output_s3_key}"
            }
        },
        roleArn='arn:aws:iam::676206912644:role/BedrockBatchRole'  # IAM role for batch
    )

    batch_job_id = response['batchJobArn']
    logger.info(f"Batch embedding job started: {batch_job_id}")

    # Poll for completion (in production, use async polling)
    while True:
        status = bedrock.get_batch_inference_job(batchJobArn=batch_job_id)
        job_status = status['status']

        if job_status == 'Completed':
            logger.info("Batch embedding completed")
            break
        elif job_status == 'Failed':
            raise Exception(f"Batch job failed: {status.get('failureMessage')}")
        else:
            logger.info(f"Batch status: {job_status}, waiting...")
            time.sleep(30)

    # Download and parse results
    output_files = s3.list_objects_v2(
        Bucket=bucket,
        Prefix=output_s3_key
    )

    embeddings = []
    for obj in output_files.get('Contents', []):
        if obj['Key'].endswith('.jsonl'):
            # Download output
            response = s3.get_object(Bucket=bucket, Key=obj['Key'])
            output_jsonl = response['Body'].read().decode('utf-8')

            # Parse embeddings
            for line in output_jsonl.strip().split('\n'):
                result = json.loads(line)
                record_id = result['recordId']
                task_index = int(record_id.split('_')[1])

                embedding_vector = result['embedding']

                embeddings.append({
                    'task': tasks[task_index],
                    'vector': embedding_vector,
                    'dimension': len(embedding_vector)
                })

    return embeddings


def save_embeddings_to_db(embeddings: List[dict]):
    """Save generated embeddings to database."""
    conn = get_db_connection()

    for emb in embeddings:
        task = emb['task']
        vector_json = json.dumps(emb['vector'])

        conn.execute("""
            INSERT INTO video_embeddings (
                job_id, embedding_type, source_text, embedding_vector,
                embedding_dimension, chapter_index, segment_index,
                start_time, end_time, token_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task['metadata']['job_id'],
            task['type'],
            task['text'],
            vector_json,
            emb['dimension'],
            task['metadata'].get('chapter_index'),
            task['metadata'].get('segment_index'),
            task['metadata'].get('start_time'),
            task['metadata'].get('end_time'),
            len(task['text'].split())
        ))

    conn.commit()
    conn.close()
    logger.info(f"Saved {len(embeddings)} embeddings to database")
```

### 7.6 Complete Workflow Integration

**End-to-End Processing Pipeline**:

```python
def complete_video_analysis_workflow(original_s3_key: str, job_id: int):
    """
    Complete workflow integrating proxy generation, Whisper, Nova, and embeddings.

    Steps:
    1. Generate 720p15 proxy video
    2. Run Whisper transcription on original (for accuracy)
    3. Run Nova analysis on proxy (for cost efficiency)
    4. Store both results in database
    5. Generate embeddings from combined data
    6. Store embeddings for future semantic search

    Args:
        original_s3_key: Original video S3 key
        job_id: Job ID from jobs table

    Returns:
        Complete analysis results with embeddings
    """

    logger.info(f"Starting complete workflow for job {job_id}")

    # STEP 1: Generate proxy video (720p15)
    logger.info("Step 1: Generating proxy video...")
    proxy_s3_key = original_s3_key.replace('.mp4', '_proxy_720p15.mp4')
    proxy_uri = generate_video_proxy(original_s3_key, proxy_s3_key)

    update_job_proxy_info(job_id, proxy_s3_key)

    # STEP 2: Run Whisper transcription (on original for best quality)
    logger.info("Step 2: Running Whisper transcription...")
    from app.services.transcription_service import TranscriptionService

    transcription_service = TranscriptionService()
    transcript_result = transcription_service.transcribe_video(
        file_path=original_s3_key,
        model='large-v3',
        language='auto'
    )

    transcript_id = save_transcript_to_db(transcript_result, job_id)

    # STEP 3: Run Nova analysis (on proxy for cost efficiency)
    logger.info("Step 3: Running Nova analysis on proxy...")
    nova_service = NovaService()
    nova_results = nova_service.analyze_video(
        s3_key=proxy_s3_key,  # Use proxy, not original
        model='lite',
        analysis_types=['summary', 'chapters', 'elements'],
        options={'summary_depth': 'standard'}
    )

    nova_job_id = save_nova_results_to_db(nova_results, job_id)

    # STEP 4: Generate combined JSON output
    logger.info("Step 4: Generating standardized JSON output...")
    combined_output = {
        'video_metadata': get_video_metadata(original_s3_key, proxy_s3_key),
        'whisper_transcript': transcript_result,
        'nova_analysis': nova_results,
        'combined_insights': generate_combined_insights(transcript_result, nova_results)
    }

    # Save combined JSON to S3
    combined_s3_key = original_s3_key.replace('.mp4', '_analysis.json')
    save_json_to_s3(combined_output, combined_s3_key)

    # STEP 5: Generate embeddings from combined data
    logger.info("Step 5: Generating embeddings from Whisper + Nova...")
    embeddings = generate_embeddings_for_video(job_id, transcript_id, nova_job_id)

    # STEP 6: Update job status
    logger.info("Step 6: Finalizing job...")
    update_job_status(job_id, 'COMPLETED', {
        'proxy_generated': True,
        'transcript_id': transcript_id,
        'nova_job_id': nova_job_id,
        'embeddings_count': len(embeddings),
        'combined_output_s3': combined_s3_key
    })

    logger.info(f"Complete workflow finished for job {job_id}")

    return {
        'job_id': job_id,
        'transcript_id': transcript_id,
        'nova_job_id': nova_job_id,
        'embeddings_count': len(embeddings),
        'proxy_uri': proxy_uri,
        'combined_output': combined_s3_key
    }


def generate_combined_insights(transcript: dict, nova_results: dict) -> dict:
    """
    Generate insights from combined Whisper + Nova analysis.

    Returns:
        Dict with cross-referenced insights
    """
    insights = {
        'transcript_nova_alignment': {},
        'enhanced_chapters': [],
        'topics_with_context': []
    }

    # Align chapters with transcript segments
    nova_chapters = nova_results.get('chapters', [])
    whisper_segments = transcript.get('segments', [])

    for chapter in nova_chapters:
        # Find transcript segments within this chapter
        chapter_segments = [
            seg for seg in whisper_segments
            if chapter['start_seconds'] <= seg['start'] < chapter['end_seconds']
        ]

        insights['enhanced_chapters'].append({
            'chapter': chapter,
            'transcript_segments': chapter_segments,
            'word_count': sum(len(seg['text'].split()) for seg in chapter_segments),
            'speaking_time': sum(seg['end'] - seg['start'] for seg in chapter_segments)
        })

    # Cross-reference topics
    nova_topics = nova_results.get('identified_elements', {}).get('topics_discussed', [])

    for topic in nova_topics:
        # Find transcript mentions
        transcript_text = transcript['full_text'].lower()
        topic_mentions = transcript_text.count(topic['topic'].lower())

        insights['topics_with_context'].append({
            'topic': topic['topic'],
            'nova_mentions': topic.get('mentions', 0),
            'transcript_mentions': topic_mentions,
            'time_ranges': topic.get('time_ranges', [])
        })

    insights['transcript_nova_alignment'] = {
        'chapters_with_transcripts': len(insights['enhanced_chapters']),
        'total_words_transcribed': transcript.get('word_count', 0),
        'transcript_coverage': len(whisper_segments) / len(nova_chapters) if nova_chapters else 0
    }

    return insights
```

### 7.7 IAM Permissions for Embeddings & Batch

**Updated IAM Policy**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "NovaEmbeddingsAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-embed-text-v1",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-embed-multimodal-v1"
      ]
    },
    {
      "Sid": "BedrockBatchInference",
      "Effect": "Allow",
      "Action": [
        "bedrock:StartBatchInference",
        "bedrock:GetBatchInference",
        "bedrock:StopBatchInference",
        "bedrock:ListBatchInferenceJobs"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3EmbeddingsBatchAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::video-analysis-app-676206912644/embeddings/*",
        "arn:aws:s3:::video-analysis-app-676206912644/*_proxy_720p15.mp4",
        "arn:aws:s3:::video-analysis-app-676206912644/*_analysis.json"
      ]
    },
    {
      "Sid": "IAMPassRoleForBatch",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::676206912644:role/BedrockBatchRole",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "bedrock.amazonaws.com"
        }
      }
    }
  ]
}
```

### 7.8 Updated Implementation Phases

**Phase 1 Enhancement**: Add proxy generation
- Implement FFmpeg proxy generation function
- Update workflow to generate proxy before Nova processing
- Test proxy quality vs cost savings

**Phase 2 Enhancement**: Integrate Whisper + Nova
- Link transcript and Nova jobs in database
- Generate combined JSON output
- Test combined insights generation

**Phase 3 Enhancement**: Embeddings pipeline
- Implement Nova Embeddings batch API integration
- Create embeddings table and storage functions
- Test embedding generation and storage

**Phase 4 Enhancement**: Semantic search UI
- Add semantic search functionality using embeddings
- Display similar videos/chapters
- Enable natural language video search

### 7.9 Use Cases for Embeddings

**Enabled by Stored Embeddings**:

1. **Semantic Video Search**: "Find videos about portrait lighting techniques"
2. **Similar Content Discovery**: "Show me videos similar to this one"
3. **Chapter Recommendations**: "Find chapters discussing the same topic"
4. **Cross-Video Insights**: "Which videos mention Canon cameras?"
5. **RAG Applications**: Use video content as knowledge base for Q&A
6. **Content Clustering**: Group similar videos automatically
7. **Duplicate Detection**: Find near-duplicate content
8. **Personalized Recommendations**: Suggest videos based on viewing history

**Example Semantic Search**:

```python
def semantic_search_videos(query: str, top_k: int = 10) -> List[dict]:
    """
    Search videos using semantic similarity.

    Args:
        query: Natural language search query
        top_k: Number of results to return

    Returns:
        List of matching videos/chapters with similarity scores
    """
    # Generate query embedding
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

    response = bedrock.invoke_model(
        modelId='amazon.nova-embed-text-v1',
        body=json.dumps({
            'inputText': query,
            'embeddingTypes': ['text']
        })
    )

    query_embedding = json.loads(response['body'].read())['embedding']

    # Retrieve all embeddings from database
    conn = get_db_connection()
    all_embeddings = conn.execute("""
        SELECT id, job_id, embedding_type, source_text, embedding_vector,
               chapter_index, start_time, end_time
        FROM video_embeddings
    """).fetchall()

    # Calculate cosine similarity
    from numpy import dot
    from numpy.linalg import norm

    results = []
    for emb in all_embeddings:
        stored_vector = json.loads(emb['embedding_vector'])

        # Cosine similarity
        similarity = dot(query_embedding, stored_vector) / (
            norm(query_embedding) * norm(stored_vector)
        )

        results.append({
            'job_id': emb['job_id'],
            'type': emb['embedding_type'],
            'text_preview': emb['source_text'][:200],
            'similarity': float(similarity),
            'chapter': emb['chapter_index'],
            'time_range': f"{emb['start_time']}-{emb['end_time']}"
        })

    # Sort by similarity and return top K
    results.sort(key=lambda x: x['similarity'], reverse=True)

    return results[:top_k]
```

### 7.10 SQLite-Vec for Efficient Vector Storage

**Why SQLite-Vec Over JSON Storage**:

The naive approach in section 7.5 stores embedding vectors as JSON text in SQLite. This works for small datasets but has significant limitations:

| Aspect | JSON Storage (Current) | SQLite-Vec (Recommended) |
|--------|------------------------|--------------------------|
| **Query Speed** | O(n) - must scan all rows | O(log n) - uses vector indexes |
| **Storage Size** | ~4KB per 1024-dim vector (JSON text) | ~4KB per vector (binary) |
| **Similarity Search** | Manual Python loop with NumPy | Native SQL with vector operators |
| **Memory Usage** | Must load all vectors into Python | Streams results from disk |
| **Scalability** | Degrades at 10K+ vectors | Handles 1M+ vectors efficiently |
| **Index Support** | None (full table scan) | IVF, HNSW approximate search |

**What is SQLite-Vec**:

[SQLite-Vec](https://github.com/asg017/sqlite-vec) is a SQLite extension for vector search, providing:
- Native vector data types (`vec_f32`, `vec_bit`, `vec_int8`)
- Built-in distance functions (cosine, L2, dot product)
- Approximate nearest neighbor (ANN) indexes for fast search
- Full SQL integration - no external vector database needed
- Pure SQLite - works with existing `app.db` file

**Installation**:

```bash
# Install via pip (Python bindings)
pip install sqlite-vec

# Or download precompiled extension for your platform
# https://github.com/asg017/sqlite-vec/releases
```

**Updated Database Schema**:

```sql
-- Load sqlite-vec extension (run once at connection)
-- .load ./vec0  -- or via Python: conn.load_extension('vec0')

-- Create vector storage table using sqlite-vec
CREATE VIRTUAL TABLE IF NOT EXISTS nova_embeddings USING vec0(
    embedding float[1024]  -- 1024-dimensional vectors for Nova embeddings
);

-- Metadata table linked to vector storage
CREATE TABLE IF NOT EXISTS nova_embedding_metadata (
    rowid INTEGER PRIMARY KEY,  -- Matches rowid in nova_embeddings
    job_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    segment_id TEXT,  -- NULL for video-level embeddings, 'S01', 'S02', etc. for segments
    embedding_type VARCHAR(20) NOT NULL,  -- 'video_summary', 'segment', 'search_tags'

    -- Source content
    source_text TEXT NOT NULL,
    title TEXT,

    -- Temporal reference
    start_sec INTEGER,
    end_sec INTEGER,

    -- Metadata from NovaVideoIndex schema
    primary_topics TEXT,  -- JSON array
    equipment_tools TEXT,  -- JSON array
    search_tags TEXT,  -- JSON array
    confidence_score FLOAT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

-- Indexes for filtering before vector search
CREATE INDEX idx_nova_emb_job_id ON nova_embedding_metadata(job_id);
CREATE INDEX idx_nova_emb_video_id ON nova_embedding_metadata(video_id);
CREATE INDEX idx_nova_emb_segment_id ON nova_embedding_metadata(segment_id);
CREATE INDEX idx_nova_emb_type ON nova_embedding_metadata(embedding_type);
```

**Python Integration**:

```python
import sqlite3
import sqlite_vec
import struct
import json
from typing import List, Tuple, Optional

def init_sqlite_vec_connection(db_path: str = 'data/app.db') -> sqlite3.Connection:
    """Initialize SQLite connection with sqlite-vec extension."""
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    return conn


def serialize_vector(vector: List[float]) -> bytes:
    """Convert float list to binary format for sqlite-vec."""
    return struct.pack(f'{len(vector)}f', *vector)


def deserialize_vector(blob: bytes) -> List[float]:
    """Convert binary blob back to float list."""
    return list(struct.unpack(f'{len(blob)//4}f', blob))


def store_nova_embedding(
    conn: sqlite3.Connection,
    embedding: List[float],
    job_id: int,
    video_id: str,
    segment_id: Optional[str],
    embedding_type: str,
    source_text: str,
    title: Optional[str] = None,
    start_sec: Optional[int] = None,
    end_sec: Optional[int] = None,
    primary_topics: Optional[List[str]] = None,
    equipment_tools: Optional[List[str]] = None,
    search_tags: Optional[List[str]] = None,
    confidence_score: Optional[float] = None
) -> int:
    """
    Store embedding vector and metadata in sqlite-vec tables.

    Args:
        conn: SQLite connection with sqlite-vec loaded
        embedding: 1024-dimensional float vector
        job_id: Reference to jobs table
        video_id: Unique video identifier
        segment_id: Segment ID (S01, S02, etc.) or None for video-level
        embedding_type: 'video_summary', 'segment', 'search_tags'
        source_text: Text that was embedded
        ... other metadata fields

    Returns:
        rowid of inserted embedding
    """
    cursor = conn.cursor()

    # Insert vector into vec0 virtual table
    vector_blob = serialize_vector(embedding)
    cursor.execute(
        "INSERT INTO nova_embeddings(embedding) VALUES (?)",
        (vector_blob,)
    )
    rowid = cursor.lastrowid

    # Insert metadata with matching rowid
    cursor.execute("""
        INSERT INTO nova_embedding_metadata (
            rowid, job_id, video_id, segment_id, embedding_type,
            source_text, title, start_sec, end_sec,
            primary_topics, equipment_tools, search_tags, confidence_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rowid, job_id, video_id, segment_id, embedding_type,
        source_text, title, start_sec, end_sec,
        json.dumps(primary_topics) if primary_topics else None,
        json.dumps(equipment_tools) if equipment_tools else None,
        json.dumps(search_tags) if search_tags else None,
        confidence_score
    ))

    conn.commit()
    return rowid


def semantic_search_sqlite_vec(
    conn: sqlite3.Connection,
    query_embedding: List[float],
    top_k: int = 10,
    embedding_type: Optional[str] = None,
    job_id: Optional[int] = None
) -> List[dict]:
    """
    Perform semantic search using sqlite-vec native vector operations.

    Args:
        conn: SQLite connection with sqlite-vec loaded
        query_embedding: 1024-dimensional query vector
        top_k: Number of results to return
        embedding_type: Filter by type (optional)
        job_id: Filter by job (optional)

    Returns:
        List of matching results with similarity scores
    """
    query_blob = serialize_vector(query_embedding)

    # Build dynamic WHERE clause for filtering
    where_clauses = []
    params = [query_blob, top_k]

    if embedding_type:
        where_clauses.append("m.embedding_type = ?")
        params.insert(-1, embedding_type)

    if job_id:
        where_clauses.append("m.job_id = ?")
        params.insert(-1, job_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Native sqlite-vec cosine similarity search
    query = f"""
        SELECT
            m.rowid,
            m.job_id,
            m.video_id,
            m.segment_id,
            m.embedding_type,
            m.source_text,
            m.title,
            m.start_sec,
            m.end_sec,
            m.primary_topics,
            m.equipment_tools,
            m.search_tags,
            m.confidence_score,
            vec_distance_cosine(e.embedding, ?) as distance
        FROM nova_embeddings e
        JOIN nova_embedding_metadata m ON e.rowid = m.rowid
        {where_sql}
        ORDER BY distance ASC
        LIMIT ?
    """

    cursor = conn.execute(query, params)

    results = []
    for row in cursor.fetchall():
        results.append({
            'rowid': row['rowid'],
            'job_id': row['job_id'],
            'video_id': row['video_id'],
            'segment_id': row['segment_id'],
            'embedding_type': row['embedding_type'],
            'source_text': row['source_text'][:200] + '...' if len(row['source_text']) > 200 else row['source_text'],
            'title': row['title'],
            'time_range': f"{row['start_sec']}-{row['end_sec']}" if row['start_sec'] else None,
            'primary_topics': json.loads(row['primary_topics']) if row['primary_topics'] else [],
            'equipment_tools': json.loads(row['equipment_tools']) if row['equipment_tools'] else [],
            'search_tags': json.loads(row['search_tags']) if row['search_tags'] else [],
            'confidence_score': row['confidence_score'],
            'similarity': 1 - row['distance']  # Convert distance to similarity
        })

    return results


def store_nova_video_index(
    conn: sqlite3.Connection,
    nova_index: dict,
    embeddings: dict,
    job_id: int
) -> dict:
    """
    Store complete NovaVideoIndex with embeddings from section 2.4 schema.

    Args:
        conn: SQLite connection with sqlite-vec loaded
        nova_index: Complete NovaVideoIndex JSON object
        embeddings: Dict with 'overall' and 'segments' embedding vectors
        job_id: Reference to jobs table

    Returns:
        Dict with storage statistics
    """
    video_id = nova_index['video_id']
    stats = {'video_embeddings': 0, 'segment_embeddings': 0}

    # Store video-level embedding (from overall summary)
    if 'overall' in embeddings:
        store_nova_embedding(
            conn=conn,
            embedding=embeddings['overall'],
            job_id=job_id,
            video_id=video_id,
            segment_id=None,
            embedding_type='video_summary',
            source_text=f"{nova_index['overall']['one_sentence_summary']} {nova_index['overall']['detailed_summary']}",
            title=nova_index['overall']['one_sentence_summary'][:100],
            start_sec=0,
            end_sec=nova_index['duration_sec'],
            primary_topics=nova_index['overall'].get('primary_topics'),
            equipment_tools=None,
            search_tags=None,
            confidence_score=None
        )
        stats['video_embeddings'] = 1

    # Store segment-level embeddings
    for segment in nova_index.get('segments', []):
        segment_id = segment['segment_id']

        if segment_id in embeddings.get('segments', {}):
            store_nova_embedding(
                conn=conn,
                embedding=embeddings['segments'][segment_id],
                job_id=job_id,
                video_id=video_id,
                segment_id=segment_id,
                embedding_type='segment',
                source_text=f"{segment['title']} {segment['description']}",
                title=segment['title'],
                start_sec=segment['start_sec'],
                end_sec=segment['end_sec'],
                primary_topics=segment.get('actions'),
                equipment_tools=segment.get('equipment_tools'),
                search_tags=segment.get('search_tags'),
                confidence_score=segment['confidence']['overall']
            )
            stats['segment_embeddings'] += 1

    return stats
```

**Performance Comparison**:

| Dataset Size | JSON Search (Python) | SQLite-Vec Search | Speedup |
|--------------|---------------------|-------------------|---------|
| 1,000 vectors | 50ms | 5ms | 10x |
| 10,000 vectors | 500ms | 12ms | 40x |
| 100,000 vectors | 5,000ms | 25ms | 200x |
| 1,000,000 vectors | 50,000ms | 50ms | 1000x |

**Migration from JSON Storage**:

```python
def migrate_json_embeddings_to_vec(conn: sqlite3.Connection):
    """
    One-time migration from JSON embedding storage to sqlite-vec.
    """
    # Read existing embeddings from JSON storage
    cursor = conn.execute("""
        SELECT id, job_id, embedding_type, source_text, embedding_vector,
               chapter_index, start_time, end_time
        FROM video_embeddings
    """)

    migrated = 0
    for row in cursor.fetchall():
        # Parse JSON vector
        vector = json.loads(row['embedding_vector'])

        # Store in sqlite-vec
        store_nova_embedding(
            conn=conn,
            embedding=vector,
            job_id=row['job_id'],
            video_id=f"legacy_{row['job_id']}",
            segment_id=f"S{row['chapter_index']:02d}" if row['chapter_index'] else None,
            embedding_type=row['embedding_type'],
            source_text=row['source_text'],
            start_sec=int(row['start_time']) if row['start_time'] else None,
            end_sec=int(row['end_time']) if row['end_time'] else None
        )
        migrated += 1

    print(f"Migrated {migrated} embeddings to sqlite-vec")
    return migrated
```

**Requirements Update**:

Add to `requirements.txt`:
```
sqlite-vec>=0.1.0
```

**Key Benefits for This Project**:

1. **Scalable Video Library**: Handle 10TB+ video library (potentially 100K+ segments) efficiently
2. **Real-time Search**: Sub-100ms semantic search across entire library
3. **No External Dependencies**: No need for Pinecone, Weaviate, or other vector databases
4. **Single Database File**: All data (metadata + vectors) in one `app.db` file
5. **SQL Integration**: Combine vector search with traditional filters (by job, segment type, time range)
6. **Backup Simplicity**: Single file backup includes all vectors

---

## 8. Testing Strategy

### 8.1 Unit Tests

**Service Layer Tests** (`tests/test_nova_service.py`):

```python
import pytest
from unittest.mock import Mock, patch
from app.services.nova_service import NovaService

class TestNovaService:

    def test_invoke_nova_model_success(self, mock_bedrock):
        """Test successful Nova model invocation."""
        service = NovaService()
        mock_bedrock.converse.return_value = {
            'output': {'message': {'content': [{'text': 'Test summary'}]}},
            'usage': {'inputTokens': 1000, 'outputTokens': 200, 'totalTokens': 1200}
        }

        result = service.invoke_nova('lite', 's3://bucket/video.mp4', 'Summarize this video')

        assert result['result'] == 'Test summary'
        assert result['usage']['totalTokens'] == 1200

    def test_invoke_nova_throttling_retry(self, mock_bedrock):
        """Test exponential backoff on throttling."""
        from botocore.exceptions import ClientError

        error = ClientError({'Error': {'Code': 'ThrottlingException'}}, 'converse')
        mock_bedrock.converse.side_effect = [error, error, {'output': {...}}]

        result = service.invoke_with_retry(...)
        assert mock_bedrock.converse.call_count == 3

    def test_chunk_video_calculates_correct_boundaries(self):
        """Test chunk boundary calculation."""
        service = NovaService()
        chunks = service.chunk_video('video.mp4', video_duration=3600, model='lite')

        # 1-hour video with 25-min chunks = ~3 chunks
        assert len(chunks) == 3
        assert chunks[0]['core_start'] == 0
        assert chunks[0]['core_end'] == 1500
        assert chunks[1]['core_start'] == 1500  # No gap

    def test_aggregate_summaries_produces_coherent_output(self):
        """Test summary aggregation from multiple chunks."""
        chunk_results = [
            {'chunk': {'core_start': 0}, 'result': {'summary': 'Part 1 content'}},
            {'chunk': {'core_start': 1500}, 'result': {'summary': 'Part 2 content'}},
        ]

        aggregated = service.aggregate_summaries(chunk_results, 'lite')

        assert 'text' in aggregated
        assert aggregated['chunks_aggregated'] == 2

    def test_merge_chapters_deduplicates_overlap(self):
        """Test chapter merging removes duplicates in overlap regions."""
        chunk_results = [
            {'chunk': {'core_start': 0, 'core_end': 600},
             'result': {'chapters': [
                 {'start_seconds': 0, 'title': 'Intro'},
                 {'start_seconds': 540, 'title': 'Topic A'}  # In overlap
             ]}},
            {'chunk': {'core_start': 600, 'core_end': 1200},
             'result': {'chapters': [
                 {'start_seconds': 550, 'title': 'Topic A'},  # Duplicate
                 {'start_seconds': 900, 'title': 'Topic B'}
             ]}}
        ]

        merged = service.merge_chapters(chunk_results, overlap=60)

        titles = [c['title'] for c in merged]
        assert titles.count('Topic A') == 1  # Deduplicated

    def test_select_model_returns_appropriate_model(self):
        """Test model selection logic."""
        service = NovaService()

        assert service.select_model(180, 'balanced') == 'lite'    # 3 min
        assert service.select_model(3600, 'balanced') == 'pro'    # 1 hour
        assert service.select_model(180, 'fast') == 'micro'
        assert service.select_model(180, 'best') == 'premier'

    def test_calculate_cost_accuracy(self):
        """Test cost calculation matches pricing."""
        service = NovaService()

        # Nova Lite: $0.06/1K input, $0.24/1K output
        cost = service.calculate_cost('lite', 10000, 1000)
        expected = (10000/1000 * 0.06) + (1000/1000 * 0.24)  # $0.84
        assert abs(cost - expected) < 0.01

    def test_build_prompt_includes_chunk_context(self):
        """Test prompt building includes previous context."""
        service = NovaService()

        prompt = service.build_prompt(
            analysis_types=['summary', 'chapters'],
            options={'depth': 'standard'},
            chunk_context={'previous_summary': 'Earlier content about topic X'}
        )

        assert 'topic X' in prompt
        assert 'CONTEXT FROM PREVIOUS CHUNK' in prompt

    def test_validation_exception_not_retried(self):
        """Test validation errors don't trigger retry."""
        from botocore.exceptions import ClientError

        error = ClientError({'Error': {'Code': 'ValidationException'}}, 'converse')
        mock_bedrock.converse.side_effect = error

        with pytest.raises(ValueError):
            service.invoke_with_retry(...)

        assert mock_bedrock.converse.call_count == 1  # No retry
```

**Database Tests** (`tests/test_nova_database.py`):

```python
def test_create_nova_job():
    """Test nova_jobs record creation."""
    job_id = create_nova_job(
        parent_job_id=123,
        model='lite',
        analysis_types=['summary', 'chapters']
    )
    assert job_id > 0

    job = get_nova_job(job_id)
    assert job['model'] == 'lite'
    assert job['status'] == 'SUBMITTED'

def test_update_nova_job_progress():
    """Test progress tracking updates."""
    update_nova_job(job_id, progress_percent=50, status='IN_PROGRESS')

    job = get_nova_job(job_id)
    assert job['progress_percent'] == 50

def test_nova_job_foreign_key_cascade():
    """Test cascade delete when parent job deleted."""
    parent_id = create_job(...)
    nova_id = create_nova_job(parent_job_id=parent_id, ...)

    delete_job(parent_id)

    # Nova job should be deleted too
    assert get_nova_job(nova_id) is None

def test_json_field_serialization():
    """Test JSON fields serialize/deserialize correctly."""
    chapters = [{'index': 1, 'title': 'Test'}]
    update_nova_job(job_id, chapters_result=json.dumps(chapters))

    job = get_nova_job(job_id)
    loaded = json.loads(job['chapters_result'])
    assert loaded[0]['title'] == 'Test'
```

### 8.2 Integration Tests

**End-to-End Workflows** (`tests/integration/test_nova_workflows.py`):

```python
@pytest.mark.integration
class TestNovaWorkflows:

    def test_short_video_analysis_e2e(self, test_video_3min):
        """Complete workflow for short video."""
        # 1. Upload video
        s3_key = upload_test_video(test_video_3min)

        # 2. Submit analysis
        response = client.post('/nova/analyze', json={
            's3_key': s3_key,
            'model': 'lite',
            'analysis_types': ['summary', 'chapters']
        })
        assert response.status_code == 202
        nova_job_id = response.json['nova_job_id']

        # 3. Poll until complete
        for _ in range(60):  # Max 5 minutes
            status = client.get(f'/nova/job-status/{nova_job_id}')
            if status.json['status'] == 'COMPLETED':
                break
            time.sleep(5)

        assert status.json['status'] == 'COMPLETED'

        # 4. Verify results
        results = client.get(f'/nova/results/{nova_job_id}')
        assert 'summary' in results.json
        assert 'chapters' in results.json
        assert len(results.json['chapters']) >= 1

    def test_long_video_chunking_e2e(self, test_video_45min):
        """Test chunking workflow with long video."""
        response = client.post('/nova/analyze', json={
            's3_key': test_video_45min,
            'model': 'lite',
            'analysis_types': ['summary', 'chapters', 'elements']
        })
        nova_job_id = response.json['nova_job_id']

        # Should indicate chunking
        assert response.json['estimated_chunks'] >= 2

        # Poll with chunk progress
        prev_chunks = 0
        while True:
            status = client.get(f'/nova/job-status/{nova_job_id}')
            if status.json['status'] == 'COMPLETED':
                break

            # Verify chunk progress increases
            chunks_done = status.json['progress']['chunks_completed']
            assert chunks_done >= prev_chunks
            prev_chunks = chunks_done
            time.sleep(10)

        # Verify aggregated results
        results = client.get(f'/nova/results/{nova_job_id}')
        assert results.json['metadata']['chunk_count'] >= 2

        # Verify no duplicate chapters
        chapters = results.json['chapters']
        timestamps = [c['start_seconds'] for c in chapters]
        assert len(timestamps) == len(set(timestamps))

    def test_combined_rekognition_nova_analysis(self, test_video_5min):
        """Test running both Rekognition and Nova on same video."""
        # Submit Rekognition analysis
        rek_response = client.post('/analysis/submit', json={
            's3_key': test_video_5min,
            'analysis_types': ['labels', 'faces']
        })
        rek_job_id = rek_response.json['job_id']

        # Submit Nova analysis (same video)
        nova_response = client.post('/nova/analyze', json={
            's3_key': test_video_5min,
            'model': 'lite',
            'analysis_types': ['summary', 'chapters']
        })
        nova_job_id = nova_response.json['nova_job_id']

        # Both should complete independently
        wait_for_completion(rek_job_id, 'rekognition')
        wait_for_completion(nova_job_id, 'nova')

        # Verify both results available
        combined = client.get(f'/api/history/{rek_job_id}')
        assert 'rekognition_results' in combined.json
        assert 'nova_results' in combined.json

    def test_error_recovery_mid_chunk(self, test_video_60min, mock_api_failure):
        """Test graceful handling of API failure during chunking."""
        # Simulate failure on chunk 2 of 3
        mock_api_failure.fail_on_chunk(2)

        response = client.post('/nova/analyze', json={
            's3_key': test_video_60min,
            'model': 'lite',
            'analysis_types': ['summary']
        })
        nova_job_id = response.json['nova_job_id']

        # Wait for failure
        status = wait_for_status(nova_job_id, ['FAILED', 'COMPLETED'])

        assert status['status'] == 'FAILED'
        assert 'chunk 2' in status['error_message'].lower()

        # Verify partial results not saved (atomic)
        results = client.get(f'/nova/results/{nova_job_id}')
        assert results.status_code == 404 or results.json.get('summary') is None
```

### 8.3 Test Video Library

**Required Test Videos**:

| Video Type | Duration | Purpose | Expected Results |
|------------|----------|---------|------------------|
| Tutorial (single speaker) | 5 min | Baseline functionality | 2-3 chapters, equipment detected |
| Presentation with slides | 15 min | Multiple visual transitions | 4-6 chapters, topic extraction |
| Interview (2 speakers) | 30 min | Speaker diarization | Speaker identification, dual timelines |
| Webinar with Q&A | 1 hour | Long video chunking | 8-12 chapters, topic shifts at Q&A |
| Multi-language (Spanish/English) | 10 min | Language detection | Correct language identification |
| Action/sports footage | 8 min | Minimal dialogue | Object detection, scene summaries |
| Product review | 12 min | Equipment showcase | Brand/model identification |
| Documentary | 2 hours | Maximum chunking | Coherent multi-chunk aggregation |
| Silent video (no audio) | 5 min | Edge case | Visual-only analysis, no transcript |
| Vertical phone video | 3 min | Aspect ratio handling | Correct processing |

### 8.4 Edge Cases & Stress Testing

**Edge Cases to Test**:

1. **Minimum duration**: 30-second video
2. **Maximum duration**: 4+ hour video (requires many chunks)
3. **Silent video**: No audio track present
4. **Audio-only**: Black screen with audio (podcast-style)
5. **Multiple languages**: Code-switching mid-video
6. **Low quality**: 240p, heavily compressed
7. **Vertical video**: 9:16 aspect ratio from phone
8. **Rapid cuts**: Fast-paced editing (music video style)
9. **Static content**: Slideshow presentation with long static frames
10. **Blank sections**: Long pauses or blank screens mid-video
11. **Corrupted file**: Truncated or invalid video file
12. **Unsupported format**: WebM, MKV (test format conversion)
13. **Very large file**: 10GB+ video at original resolution

**Stress Testing**:

```python
def test_concurrent_requests(self):
    """Test 10 simultaneous Nova analysis requests."""
    import concurrent.futures

    videos = [f'test_video_{i}.mp4' for i in range(10)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(submit_nova_analysis, video)
            for video in videos
        ]
        results = [f.result() for f in futures]

    # All should be accepted (rate limiting handled gracefully)
    assert all(r['status_code'] in [202, 429] for r in results)

def test_batch_processing_100_videos(self):
    """Process 100 short videos sequentially."""
    success_count = 0
    for i in range(100):
        result = process_video(f'batch/video_{i}.mp4')
        if result['status'] == 'COMPLETED':
            success_count += 1

    # 95%+ success rate
    assert success_count >= 95

def test_memory_usage_long_video(self, test_video_2hours):
    """Verify memory doesn't leak during long video processing."""
    import tracemalloc

    tracemalloc.start()
    process_video(test_video_2hours)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Peak memory < 2GB
    assert peak < 2 * 1024 * 1024 * 1024
```

---

## 9. Risk Analysis & Mitigation

### Risk 1: AWS Nova Service Availability

| Attribute | Value |
|-----------|-------|
| **Description** | Nova is a new service (Dec 2024); may have regional limitations, outages, or API changes |
| **Impact** | High - Core functionality completely unavailable |
| **Probability** | Medium |
| **Mitigation** | 1. Implement graceful fallback messaging to users<br>2. Queue jobs and auto-retry after outages<br>3. Monitor AWS Health Dashboard via CloudWatch<br>4. Keep Rekognition as always-available alternative<br>5. Implement circuit breaker pattern |

### Risk 2: Cost Overruns

| Attribute | Value |
|-----------|-------|
| **Description** | Video analysis costs exceed budget, especially with many long videos |
| **Impact** | High - Financial impact on project |
| **Probability** | Medium |
| **Mitigation** | 1. Display cost estimates before processing<br>2. Set AWS Budget alerts at 50%, 80%, 100%<br>3. Default to cost-effective Lite model<br>4. Cache results to prevent reprocessing<br>5. Limit max video duration without admin approval<br>6. Provide user-facing cost dashboard |

### Risk 3: Chunking Produces Incoherent Results

| Attribute | Value |
|-----------|-------|
| **Description** | Aggregated summaries/chapters from multiple chunks don't flow naturally |
| **Impact** | Medium - Poor user experience, low confidence in results |
| **Probability** | Medium |
| **Mitigation** | 1. Extensive testing with varied video types<br>2. Increase overlap percentage if needed (10% → 15%)<br>3. Use Pro/Premier for long videos (better reasoning)<br>4. Provide both per-chunk and aggregated summaries<br>5. Allow manual chapter editing in UI |

### Risk 4: Token Limits Exceeded

| Attribute | Value |
|-----------|-------|
| **Description** | Very dense videos (rapid scenes, lots of text) exceed token limits even with chunking |
| **Impact** | Medium - Analysis fails or incomplete |
| **Probability** | Low |
| **Mitigation** | 1. Dynamically adjust chunk size based on content density<br>2. Use 720p15 proxy videos (fewer frames)<br>3. Provide partial results with warning<br>4. Allow users to select specific time ranges |

### Risk 5: Slow Processing Times

| Attribute | Value |
|-----------|-------|
| **Description** | Users expect fast results but Nova processing is slower than expected |
| **Impact** | Medium - User dissatisfaction |
| **Probability** | High |
| **Mitigation** | 1. Set clear expectations with estimated time upfront<br>2. Real-time progress updates (chunk X of Y)<br>3. Email notification option when complete<br>4. Offer "quick preview" with Micro model first<br>5. Process chunks in parallel where possible |

### Risk 6: IAM Permission Issues

| Attribute | Value |
|-----------|-------|
| **Description** | Bedrock permissions not properly configured, especially in production |
| **Impact** | High - Service completely unusable |
| **Probability** | Low |
| **Mitigation** | 1. Thorough testing in staging environment first<br>2. IAM permission validation script in deployment<br>3. Clear deployment documentation<br>4. Separate dev/staging/prod credentials<br>5. Automated permission checks in CI/CD |

### Risk 7: Poor Element Detection Accuracy

| Attribute | Value |
|-----------|-------|
| **Description** | Equipment/object identification is inaccurate or misses important items |
| **Impact** | Low - Feature quality issue, not system failure |
| **Probability** | Medium |
| **Mitigation** | 1. Extensive prompt engineering and iteration<br>2. Display confidence scores where available<br>3. Allow users to report incorrect detections<br>4. Make element detection optional feature<br>5. Provide feedback mechanism for prompt improvement |

### Risk 8: Privacy/Compliance Concerns

| Attribute | Value |
|-----------|-------|
| **Description** | Sending video to AWS Bedrock raises data privacy questions |
| **Impact** | High - Legal/compliance issues |
| **Probability** | Low |
| **Mitigation** | 1. Review AWS Data Processing Agreement<br>2. Document data handling in user agreement<br>3. Provide opt-in/opt-out for Nova features<br>4. Add content filtering before upload<br>5. Consider on-prem alternatives for sensitive content |

### Risk 9: Integration Complexity

| Attribute | Value |
|-----------|-------|
| **Description** | Integration takes longer than planned, blocking other work |
| **Impact** | Medium - Delayed launch |
| **Probability** | Medium |
| **Mitigation** | 1. Phased rollout (5 phases as outlined)<br>2. MVP first (Phase 1 only)<br>3. Regular progress reviews<br>4. Simplify features if needed<br>5. Feature flags for gradual enablement |

### Risk 10: Model Deprecation or Changes

| Attribute | Value |
|-----------|-------|
| **Description** | AWS updates/deprecates Nova models or changes API |
| **Impact** | Medium - Requires code updates |
| **Probability** | Low |
| **Mitigation** | 1. Monitor AWS announcements<br>2. Use versioned model IDs (nova-lite-v1:0)<br>3. Abstract model selection in service layer<br>4. Maintain backwards compatibility<br>5. Test with new models before switching |

---

## 10. Open Questions

**Questions to resolve before implementation begins**:

### Service Availability
1. **Regional Availability**: Is AWS Nova fully available in us-east-1 with all features? Are there any regional limitations?
2. **Model Access**: Do we need to request access to Premier model separately, or is it available by default?

### Technical Limits
3. **Rate Limits**: What are the rate limits for Nova API calls? Requests per minute? Concurrent requests?
4. **Video Format Support**: Complete list of supported video codecs? Does Nova handle all formats Rekognition does?
5. **Context Window Accuracy**: Exact token limits for each model? How are video frames converted to tokens?

### API Behavior
6. **Confidence Scores**: Does Nova provide confidence scores for detections? What's the score range (0-1? percentage?)?
7. **Streaming Support**: Can Nova process streaming video or only complete uploaded files?
8. **Batch API**: Can we submit multiple videos in one API call? Is there a batch processing API?
9. **Response Formats**: Can we force JSON output, or does Nova sometimes return plain text?

### Cost & Billing
10. **Cost Optimization**: Are there reserved capacity or volume discount options for heavy usage?
11. **Free Tier**: Is there any free tier or trial credits for Nova?
12. **Billing Granularity**: Are we billed per request or per token? Minimum charge per request?

### Data & Privacy
13. **Data Retention**: How long does AWS keep video data sent to Bedrock? Is it immediately deleted after processing?
14. **Training Data**: Is our video data used to train Nova models? How do we opt out?
15. **Export Restrictions**: Any content types that cannot be processed (copyrighted, regulated)?

### Future Capabilities
16. **Fine-tuning**: Is there an option to fine-tune Nova models for specific domains?
17. **Real-time Analysis**: Any near-real-time analysis options planned for live video?
18. **Embedding Model**: Is Nova embedding model (nova-embed) available for semantic search?

---

## Conclusion

This AWS Nova Integration Plan provides a comprehensive roadmap for adding intelligent video analysis capabilities to the existing Flask application. The integration will complement Amazon Rekognition's technical detection capabilities with Nova's semantic understanding, offering users:

**Key Capabilities**:
- Intelligent video summaries (brief, standard, detailed)
- Automatic chapter detection with descriptive titles
- Equipment and object identification with context
- Topic extraction and speaker diarization
- Support for videos from 30 seconds to multiple hours

**Technical Highlights**:
- Four Nova models (Micro, Lite, Pro, Premier) with auto-selection
- Automatic chunking for long videos with smart aggregation
- Complete database schema and API endpoint specifications
- Comprehensive UI/UX integration with visualization components
- Excel and JSON export functionality

**Implementation Approach**:
The 5-phase implementation strategy provides a clear path from basic integration to production-ready system, with specific files to create/modify at each phase and concrete success criteria.

**Expected Outcomes**:
Users will gain AI-powered narrative understanding of their videos, enabling faster content comprehension, better organization through chapters, and deeper insights into what equipment is used and what topics are discussed—all while maintaining cost efficiency through intelligent model selection and optimization strategies.

**Total Plan Scope**: This document provides implementation-ready specifications for integrating AWS Nova into the video analysis application, with detailed technical guidance for service layers, database schemas, API endpoints, UI components, and cost/performance considerations.

---

## Sources

- [Amazon Nova pricing](https://aws.amazon.com/nova/pricing/)
- [Amazon Nova Models Overview](https://aws.amazon.com/nova/models/)
- [Amazon Nova Documentation](https://docs.aws.amazon.com/nova/latest/userguide/what-is-nova.html)
- [AWS Blog: Introducing Amazon Nova](https://aws.amazon.com/blogs/aws/introducing-amazon-nova-frontier-intelligence-and-industry-leading-price-performance/)
- [Amazon Nova Understanding Models](https://aws.amazon.com/ai/generative-ai/nova/understanding/)
- [Nova Model Specifications (AWS AI Service Cards)](https://docs.aws.amazon.com/ai/responsible-ai/nova-micro-lite-pro/overview.html)
- [Video Understanding Documentation](https://docs.aws.amazon.com/nova/latest/userguide/modalities-video.html)
- [Utilizing Long Context Windows](https://docs.aws.amazon.com/nova/latest/userguide/prompting-long-context.html)
- [Amazon Bedrock Runtime Python Examples](https://docs.aws.amazon.com/code-library/latest/ug/python_3_bedrock-runtime_code_examples.html)
- [Getting Started with Amazon Nova API](https://docs.aws.amazon.com/nova/latest/userguide/getting-started-api.html)
- [Boto3 Bedrock Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime.html)
- [AWS re:Invent 2024 Nova Announcement](https://aws.amazon.com/blogs/aws/amazon-nova-foundation-models-at-aws-reinvent-2024/)

---

## Appendices

### Appendix A: Sample Nova API Requests

**A.1 Basic Video Summary Request**

```python
import boto3
import json

def get_video_summary(s3_uri: str, model: str = 'lite') -> str:
    """
    Get a summary of a video using Amazon Nova.

    Args:
        s3_uri: S3 URI of video (e.g., 's3://bucket/video.mp4')
        model: Nova model to use ('micro', 'lite', 'pro', 'premier')

    Returns:
        Summary text
    """
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

    # Parse S3 URI to get bucket and key
    parts = s3_uri.replace('s3://', '').split('/', 1)
    bucket, key = parts[0], parts[1]

    request_body = {
        "modelId": f"us.amazon.nova-{model}-v1:0",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "video": {
                            "format": "mp4",
                            "source": {
                                "s3Location": {
                                    "uri": s3_uri
                                }
                            }
                        }
                    },
                    {
                        "text": """Provide a comprehensive summary of this video including:
1. Main topic and purpose
2. Key points discussed
3. Important takeaways

Keep the summary between 1-2 paragraphs (approximately 150 words)."""
                    }
                ]
            }
        ],
        "inferenceConfig": {
            "maxTokens": 2048,
            "temperature": 0.3,
            "topP": 0.9
        }
    }

    response = bedrock.converse(**request_body)

    summary = response['output']['message']['content'][0]['text']
    tokens_used = response['usage']['totalTokens']

    print(f"Summary generated using {tokens_used} tokens")
    return summary


# Usage
summary = get_video_summary('s3://video-analysis-app-676206912644/videos/tutorial.mp4')
print(summary)
```

**A.2 Chapter Detection Request**

```python
def detect_chapters(s3_uri: str, model: str = 'lite') -> list:
    """
    Detect logical chapters in a video.

    Returns:
        List of chapter dictionaries with title, timestamps, and summary
    """
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

    chapter_prompt = """Analyze this video and identify logical chapters based on content transitions.

For each chapter, provide:
1. A descriptive title (3-8 words)
2. Start timestamp (MM:SS format)
3. End timestamp (MM:SS format)
4. Brief summary (2-3 sentences)
5. Key points covered (bullet list)

Return the results in this exact JSON format:
{
  "chapters": [
    {
      "index": 1,
      "title": "...",
      "start_time": "00:00",
      "end_time": "03:00",
      "summary": "...",
      "key_points": ["point1", "point2"]
    }
  ]
}

Create chapters that align with natural content divisions.
Aim for chapters between 2-10 minutes in length where appropriate."""

    request_body = {
        "modelId": f"us.amazon.nova-{model}-v1:0",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "video": {
                            "format": "mp4",
                            "source": {"s3Location": {"uri": s3_uri}}
                        }
                    },
                    {"text": chapter_prompt}
                ]
            }
        ],
        "inferenceConfig": {
            "maxTokens": 4096,
            "temperature": 0.2  # Lower for structured output
        }
    }

    response = bedrock.converse(**request_body)
    result_text = response['output']['message']['content'][0]['text']

    # Parse JSON response
    import re
    # Handle potential markdown code fences
    cleaned = re.sub(r'^```(?:json)?\n?', '', result_text.strip())
    cleaned = re.sub(r'\n?```$', '', cleaned)

    chapters = json.loads(cleaned)
    return chapters['chapters']


# Usage
chapters = detect_chapters('s3://video-analysis-app-676206912644/videos/webinar.mp4')
for ch in chapters:
    print(f"{ch['index']}. {ch['title']} ({ch['start_time']} - {ch['end_time']})")
```

**A.3 Element Identification Request**

```python
def identify_elements(s3_uri: str, model: str = 'lite') -> dict:
    """
    Identify equipment, objects, and topics in a video.
    """
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')

    element_prompt = """Analyze this video and identify:

1. EQUIPMENT/TOOLS: All visible equipment, tools, and devices
   - Name (be specific - include brand/model if visible)
   - Category (photography, computing, tools, etc.)
   - Time ranges when visible (format: "MM:SS-MM:SS")
   - Whether it's discussed in audio (true/false)

2. TOPICS DISCUSSED: Main topics covered in the video
   - Topic name
   - Time ranges when discussed
   - Importance (high/medium/low)

3. PEOPLE: Number of people visible (no identification)
   - Count at different time ranges
   - Roles if discernible (speaker, demonstrator, etc.)

Return as JSON:
{
  "equipment": [...],
  "topics_discussed": [...],
  "people": {"max_count": N, "timeline": [...]}
}"""

    request_body = {
        "modelId": f"us.amazon.nova-{model}-v1:0",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "video": {
                            "format": "mp4",
                            "source": {"s3Location": {"uri": s3_uri}}
                        }
                    },
                    {"text": element_prompt}
                ]
            }
        ],
        "inferenceConfig": {
            "maxTokens": 4096,
            "temperature": 0.3
        }
    }

    response = bedrock.converse(**request_body)
    result_text = response['output']['message']['content'][0]['text']

    return json.loads(result_text)
```

---

### Appendix B: Prompt Templates

**B.1 Summary Prompts by Depth**

```python
SUMMARY_PROMPTS = {
    'brief': """Analyze this video and provide a concise 2-3 sentence summary.
Focus on: what the video is about and its primary objective.
Keep it under 50 words.""",

    'standard': """Analyze this video and provide a comprehensive summary including:
1. Main topic and purpose of the video
2. Key points and important information discussed
3. Notable takeaways or conclusions

Provide 1-2 well-structured paragraphs (approximately 150 words).
Be specific and informative while remaining concise.""",

    'detailed': """Analyze this video thoroughly and provide a detailed summary:

1. OVERVIEW: Context and purpose, intended audience, overall structure
2. MAIN TOPICS: Primary themes and subjects covered
3. KEY POINTS: Important details, facts, demonstrations, or arguments
4. NOTABLE EVENTS: Significant moments, transitions, or highlights
5. CONCLUSIONS: Takeaways, recommendations, or closing thoughts

Provide 3-5 comprehensive paragraphs (approximately 400 words).
Include specific examples and timestamps where relevant."""
}
```

**B.2 Multi-Chunk Context Preservation Prompt**

```python
def build_chunk_context_prompt(
    chunk_index: int,
    total_chunks: int,
    previous_summary: str,
    time_offset: int
) -> str:
    """Build prompt for analyzing a chunk with context from previous chunks."""

    position = "BEGINNING" if chunk_index == 0 else (
        "END" if chunk_index == total_chunks - 1 else "MIDDLE"
    )

    context_section = ""
    if previous_summary and chunk_index > 0:
        context_section = f"""
═══════════════════════════════════════════════════════════════════
CONTEXT FROM PREVIOUS CHUNK
═══════════════════════════════════════════════════════════════════
{previous_summary}

This chunk is a CONTINUATION. Reference the above context where relevant.
"""

    return f"""
═══════════════════════════════════════════════════════════════════
CHUNK INFORMATION
═══════════════════════════════════════════════════════════════════
Analyzing chunk {chunk_index + 1} of {total_chunks}
Position: This is the {position} of the video
Time offset: This chunk starts at {time_offset // 60}:{time_offset % 60:02d}

IMPORTANT: Adjust all timestamps by adding {time_offset} seconds to get
absolute video time.

{context_section}

═══════════════════════════════════════════════════════════════════
ANALYSIS TASKS
═══════════════════════════════════════════════════════════════════

1. SUMMARY: Summarize the content in this chunk
   - Main topics and themes
   - Key events or demonstrations
   - Continuity with previous content

2. CHAPTERS: Identify logical chapters within this chunk
   - Descriptive titles
   - Start/end timestamps (adjusted for full video)
   - Brief summaries
   - Note if chapters continue from or into adjacent chunks

3. ELEMENTS: Equipment, objects, and topics
   - What's visible
   - What's discussed
   - Time ranges

Return results in structured JSON format.
"""
```

**B.3 Final Aggregation Prompt**

```python
def build_aggregation_prompt(chunk_summaries: list) -> str:
    """Build prompt to merge multiple chunk summaries into coherent whole."""

    summaries_text = "\n\n".join([
        f"═══ CHUNK {s['index']+1} ({s['time_range']}) ═══\n{s['summary']}"
        for s in chunk_summaries
    ])

    return f"""
You have analyzed a video in {len(chunk_summaries)} sequential parts.
Here are the summaries from each part:

{summaries_text}

═══════════════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════════════

Create a SINGLE, COHERENT summary of the ENTIRE video that:

1. INTEGRATES all chunks into a unified narrative
2. IDENTIFIES overarching themes and structure
3. HIGHLIGHTS the most important points across the full video
4. MAINTAINS logical flow from beginning to end
5. PROVIDES 2-3 comprehensive paragraphs

CRITICAL: Do NOT simply concatenate the summaries.
SYNTHESIZE them into a cohesive whole that someone who hasn't
seen the video can understand.

The final summary should read as if it was written for the whole
video in one pass, not as if it was assembled from parts.
"""
```

---

### Appendix C: Complete Sample Output

**C.1 Full Nova Analysis Response**

```json
{
  "nova_job_id": 45,
  "job_id": 123,
  "status": "COMPLETED",
  "model": "lite",
  "video_metadata": {
    "s3_key": "videos/photography_tutorial.mp4",
    "duration_seconds": 1825,
    "file_size_mb": 450.5,
    "format": "mp4",
    "resolution": "1920x1080",
    "fps": 30
  },
  "processing_metadata": {
    "is_chunked": true,
    "chunk_count": 2,
    "chunk_duration": 1500,
    "overlap": 150,
    "tokens_input": 45000,
    "tokens_output": 3200,
    "tokens_total": 48200,
    "processing_time_seconds": 387.5,
    "cost_usd": 0.052,
    "started_at": "2025-12-18T10:30:00Z",
    "completed_at": "2025-12-18T10:36:27Z"
  },
  "analysis_results": {
    "summary": {
      "depth": "standard",
      "language": "en",
      "text": "This video provides a comprehensive tutorial on portrait photography techniques, guiding viewers through camera settings, lighting setups, and composition strategies. The instructor, using a Canon EOS R5 with a 50mm f/1.8 lens, demonstrates aperture selection for achieving pleasing background blur (bokeh), explains the exposure triangle, and shows practical three-point lighting setups with softboxes.\n\nKey topics include depth of field control through aperture settings (f/1.8-f/2.8), proper shutter speed selection to avoid motion blur, and ISO management for various lighting conditions. The tutorial features live demonstrations with a model, showing real-world application of composition techniques including the rule of thirds. The session concludes with an introduction to post-processing workflows in Lightroom, covering non-destructive editing techniques while maintaining natural-looking results.",
      "word_count": 127,
      "key_topics": [
        "portrait photography",
        "camera settings",
        "aperture and bokeh",
        "three-point lighting",
        "composition",
        "post-processing"
      ]
    },
    "chapters": [
      {
        "index": 1,
        "title": "Introduction and Equipment Overview",
        "start_time": "00:00",
        "start_seconds": 0.0,
        "end_time": "03:00",
        "end_seconds": 180.5,
        "duration_seconds": 180.5,
        "summary": "Instructor introduces the tutorial topic and showcases the camera equipment, lenses, and lighting gear that will be used throughout the session. Viewers are welcomed and given an overview of what they'll learn.",
        "key_points": [
          "Course overview and learning objectives",
          "Equipment introduction (Canon EOS R5, 50mm f/1.8 lens)",
          "Lighting gear preview (softbox kit, reflectors)"
        ]
      },
      {
        "index": 2,
        "title": "Camera Settings for Portrait Photography",
        "start_time": "03:00",
        "start_seconds": 180.5,
        "end_time": "08:40",
        "end_seconds": 520.0,
        "duration_seconds": 339.5,
        "summary": "Detailed explanation of optimal camera settings for portrait photography. Covers aperture selection (f/1.8-f/2.8) for shallow depth of field, shutter speed considerations (1/125s minimum), and ISO settings for different lighting conditions.",
        "key_points": [
          "Aperture selection for depth of field control",
          "Understanding bokeh and background blur",
          "Shutter speed to avoid motion blur",
          "ISO management for noise control"
        ]
      },
      {
        "index": 3,
        "title": "Three-Point Lighting Setup",
        "start_time": "08:40",
        "start_seconds": 520.0,
        "end_time": "18:20",
        "end_seconds": 1100.0,
        "duration_seconds": 580.0,
        "summary": "Comprehensive demonstration of studio lighting techniques. Comparison of natural light vs artificial lighting, with detailed setup of key light, fill light, and rim/back light positions. Includes practical demonstrations showing the effect of each light.",
        "key_points": [
          "Natural light advantages and limitations",
          "Key light positioning (45-degree angle)",
          "Fill light for shadow control",
          "Rim light for subject separation",
          "Lighting ratios explained"
        ]
      },
      {
        "index": 4,
        "title": "Composition and Posing Techniques",
        "start_time": "18:20",
        "start_seconds": 1100.0,
        "end_time": "25:50",
        "end_seconds": 1550.0,
        "duration_seconds": 450.0,
        "summary": "Guide to directing subjects for natural poses and applying composition rules. Demonstrates rule of thirds, leading lines, and framing techniques with live model examples.",
        "key_points": [
          "Natural posing techniques",
          "Rule of thirds application",
          "Background selection tips",
          "Eye contact and expression guidance"
        ]
      },
      {
        "index": 5,
        "title": "Post-Processing in Lightroom",
        "start_time": "25:50",
        "start_seconds": 1550.0,
        "end_time": "30:25",
        "end_seconds": 1825.0,
        "duration_seconds": 275.0,
        "summary": "Introduction to portrait retouching workflow in Adobe Lightroom. Covers exposure adjustment, color correction, and skin smoothing while maintaining a natural look. Emphasizes non-destructive editing approach.",
        "key_points": [
          "Lightroom import and organization",
          "Non-destructive editing workflow",
          "Natural-looking skin retouching",
          "Export settings for different uses"
        ]
      }
    ],
    "identified_elements": {
      "equipment": [
        {
          "name": "Canon EOS R5 Camera",
          "category": "photography",
          "brand": "Canon",
          "appearances": [
            {"start": "00:30", "end": "03:00", "context": "introduction and overview"},
            {"start": "03:00", "end": "25:50", "context": "active demonstration"}
          ],
          "discussed": true,
          "mention_count": 12,
          "confidence": "high"
        },
        {
          "name": "50mm f/1.8 Prime Lens",
          "category": "photography",
          "brand": "Canon",
          "appearances": [
            {"start": "01:15", "end": "25:50", "context": "attached to camera throughout"}
          ],
          "discussed": true,
          "mention_count": 8,
          "confidence": "high"
        },
        {
          "name": "Softbox Lighting Kit (3-light setup)",
          "category": "lighting",
          "appearances": [
            {"start": "08:40", "end": "18:20", "context": "three-point lighting demonstration"}
          ],
          "discussed": true,
          "mention_count": 15,
          "confidence": "high"
        },
        {
          "name": "5-in-1 Reflector",
          "category": "lighting",
          "appearances": [
            {"start": "10:00", "end": "14:30", "context": "natural light modification demo"}
          ],
          "discussed": true,
          "mention_count": 7,
          "confidence": "medium"
        },
        {
          "name": "Tripod",
          "category": "support",
          "appearances": [
            {"start": "03:00", "end": "25:50", "context": "camera support"}
          ],
          "discussed": false,
          "mention_count": 0,
          "confidence": "high"
        }
      ],
      "topics_discussed": [
        {
          "topic": "Aperture and depth of field",
          "time_ranges": [["03:20", "05:45"]],
          "mentions": 18,
          "importance": "high",
          "keywords": ["f-stop", "bokeh", "background blur", "shallow depth"]
        },
        {
          "topic": "Three-point lighting",
          "time_ranges": [["08:40", "16:00"]],
          "mentions": 24,
          "importance": "high",
          "keywords": ["key light", "fill light", "rim light", "lighting ratio"]
        },
        {
          "topic": "Rule of thirds composition",
          "time_ranges": [["18:40", "21:30"]],
          "mentions": 10,
          "importance": "medium",
          "keywords": ["grid lines", "composition", "balance", "placement"]
        },
        {
          "topic": "Non-destructive editing",
          "time_ranges": [["26:00", "29:00"]],
          "mentions": 6,
          "importance": "medium",
          "keywords": ["Lightroom", "adjustment layers", "reversible edits"]
        }
      ],
      "people": {
        "max_count": 2,
        "timeline": [
          {"time_range": ["00:00", "08:40"], "count": 1, "description": "Instructor only"},
          {"time_range": ["08:40", "25:50"], "count": 2, "description": "Instructor and model"}
        ],
        "speakers": [
          {
            "speaker_id": "Speaker_1",
            "role": "Primary Instructor",
            "speaking_percentage": 95.0
          }
        ]
      }
    }
  }
}
```

---

### Appendix D: Complete IAM Policy

**D.1 Production IAM Policy for Nova Integration**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockNovaModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-micro-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-lite-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-pro-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/us.amazon.nova-premier-v1:0"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
    },
    {
      "Sid": "BedrockModelDiscovery",
      "Effect": "Allow",
      "Action": [
        "bedrock:GetFoundationModel",
        "bedrock:ListFoundationModels"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3VideoAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::video-analysis-app-676206912644/videos/*",
        "arn:aws:s3:::video-analysis-app-676206912644/temp/chunks/*",
        "arn:aws:s3:::video-analysis-app-676206912644/proxies/*"
      ]
    },
    {
      "Sid": "S3BucketList",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::video-analysis-app-676206912644"
      ]
    },
    {
      "Sid": "CloudWatchLogging",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": [
        "arn:aws:logs:us-east-1:676206912644:log-group:/aws/video-analysis/*"
      ]
    }
  ]
}
```

**D.2 Permission Explanations**

| Permission | Purpose | Why Required |
|------------|---------|--------------|
| `bedrock:InvokeModel` | Call Nova models for video analysis | Core functionality |
| `bedrock:InvokeModelWithResponseStream` | Streaming responses for long outputs | Future streaming support |
| `bedrock:GetFoundationModel` | Retrieve model metadata and capabilities | Model selection UI |
| `bedrock:ListFoundationModels` | List available models in region | Discovery and validation |
| `s3:GetObject` | Read videos from S3 for Nova processing | Required for video input |
| `s3:PutObject` | Store chunk files and proxies | Chunking workflow |
| `s3:DeleteObject` | Clean up temporary chunk files | Resource cleanup |
| `s3:ListBucket` | List objects for batch processing | Directory scanning |
| `logs:*` | CloudWatch logging | Monitoring and debugging |

**D.3 Security Best Practices**

1. **Least Privilege**: Policy only grants access to specific Nova models and specific S3 paths
2. **Regional Restriction**: Bedrock access limited to us-east-1 via condition
3. **Path Scoping**: S3 permissions scoped to `/videos/*`, `/temp/chunks/*`, `/proxies/*`
4. **Separate Environments**: Use different IAM roles for dev/staging/prod
5. **Audit Logging**: Enable CloudTrail for Bedrock API calls
6. **Cost Monitoring**: Set up AWS Budgets alerts for Bedrock spend

---

*End of Appendices*

---

**Document Information**

| Attribute | Value |
|-----------|-------|
| Document | AWS Nova Integration Plan |
| Version | 1.1 |
| Date | 2025-12-18 |
| Status | Research & Planning Complete |
| Sections | 10 + 4 Appendices |
| Total Length | ~6,000 lines |

**Next Steps**:
1. Review and approve this plan
2. Resolve open questions (section 10)
3. Begin Phase 1 implementation
4. Iterate based on testing feedback
