# Program Specification: Video (AWS Analysis)

## 1. Executive Summary & Project Goals

**Purpose:**
The AWS Video & Image Analysis Application is a powerful tool leveraging Amazon Rekognition to extract metadata from visual media. It serves as a content intelligence system, identifying objects, celebrities, text, and faces in videos and images uploaded by the user.

**Target Audience:**
*   **Media Managers:** Indexing large video libraries for search.
*   **Safety Officers:** Checking content for unsafe or inappropriate material.

**Success Metrics:**
*   **Performance:** Uploads 10GB videos to S3 without timeout (using Presigned URLs).
*   **Accuracy:** Correctly identifies known celebrities and faces in collections.
*   **Usability:** Simple "Select & Analyze" workflow.

## 2. User Personas & User Stories

**Personas:**
*   **The Archivist:** Has a hard drive of raw footage and needs to know "Which clips have Kevin in them?"
*   **The Compliance Officer:** Needs to scan all uploads for PPE compliance (hard hats/vests).

**User Stories:**
*   *As a User*, I want to upload a large video file directly to the cloud without it going through the local web server first (to avoid timeouts).
*   *As a User*, I want to create a "Face Collection" of my team members so I can tag them in videos.
*   *As a User*, I want to search for "Waterfalls" and find all images containing a waterfall.
*   *As a User*, I want to see a history of all jobs I've run and their results.

## 3. Functional Requirements

### 3.1. File Management
*   **Direct-to-S3 Upload:** Generate Presigned POST URLs for secure, direct browser uploads.
*   **Listing:** Sync file list from S3 bucket.
*   **Deleting:** Remove files from S3 and local DB.

### 3.2. Analysis Engines (Amazon Rekognition)
*   **Video (Async):**
    *   Start Job -> Poll Status -> Get Results.
    *   Types: Label, Face, Celebrity, Content Moderation, Text, Shot Segmentation, Person Tracking.
*   **Image (Sync):**
    *   Immediate API response.
    *   Types: Label, Face, Celebrity, Moderation, Text, PPE, Custom Labels.

### 3.3. Face Collections
*   **Management:** Create/Delete Collections.
*   **Indexing:** Add faces from images to a collection.
*   **Search:** Search a video for faces matching a collection.

### 3.4. Interfaces
*   **Web UI:** Flask + Bootstrap.
    *   Upload Page (Dropzone.js).
    *   Analysis Pages (Dropdown selection of files).
    *   Results Page (JSON viewer / Visualizer).
    *   History Page (Job tracking).

## 4. Non-Functional Requirements (NFRs)

*   **Scalability:** Async video analysis allows processing long videos without blocking the server.
*   **Security:** AWS Credentials stored in `.env`. S3 CORS configured for security.
*   **Cost:** Only run analysis when explicitly requested (Rekognition is pay-per-use).

## 5. Technical Constraints & Architecture

**Tech Stack:**
*   **Language:** Python 3.12+
*   **Framework:** Flask.
*   **AWS SDK:** `boto3`.
*   **Database:** SQLite (for job history and metadata).
*   **Frontend:** HTML/JS/CSS.

**Architecture:**
*   **Client:** Handles uploads to S3 directly.
*   **Server:** Orchestrates Rekognition jobs, stores metadata, and serves the UI.
*   **AWS:** S3 (Storage), Rekognition (Analysis).

## 6. UI/UX Design

*   **Clean:** standard Bootstrap theme.
*   **Feedback:** Progress bars for uploads. Status badges (IN_PROGRESS, SUCCEEDED) for video jobs.
*   **Visuals:** Draw bounding boxes on images for detected labels/faces (using Canvas or overlay divs).

## 7. Data Models

**MediaFile:**
*   `id`: Integer
*   `filename`: String
*   `s3_key`: String
*   `media_type`: Enum (Video, Image)
*   `uploaded_at`: Timestamp

**AnalysisJob:**
*   `job_id`: String (AWS Job ID)
*   `media_file_id`: FK
*   `analysis_type`: String
*   `status`: Enum (IN_PROGRESS, SUCCEEDED, FAILED)
*   `results_json`: JSON

## 8. Acceptance Criteria

*   **Upload:** 1GB file uploads successfully and appears in the file list.
*   **Label Analysis:** Analyzing an image of a dog returns "Dog" and "Animal" labels with confidence scores.
*   **Face Search:** Searching a video with a known face collection identifies the person and timestamps.
