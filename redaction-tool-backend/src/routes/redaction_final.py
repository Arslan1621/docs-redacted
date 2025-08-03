from flask import Blueprint, request, jsonify, send_file, Response
from werkzeug.utils import secure_filename
import os
import tempfile
import json
import zipfile
import xml.etree.ElementTree as ET
import io
import time
import uuid

redaction_bp = Blueprint('redaction', __name__)

UPLOAD_FOLDER = tempfile.gettempdir()
ALLOWED_EXTENSIONS = {'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_docx(docx_path):
    """Extract text from DOCX file using zipfile and XML parsing"""
    try:
        with zipfile.ZipFile(docx_path, 'r') as zip_file:
            # Read the main document XML
            doc_xml = zip_file.read('word/document.xml')
            
            # Parse XML
            root = ET.fromstring(doc_xml)
            
            # Define namespace
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            # Extract paragraphs
            paragraphs = []
            for para in root.findall('.//w:p', ns):
                text_content = ''
                for text_elem in para.findall('.//w:t', ns):
                    if text_elem.text:
                        text_content += text_elem.text
                
                # Include empty paragraphs to maintain structure
                paragraphs.append({
                    'type': 'paragraph',
                    'text': text_content,
                    'id': len(paragraphs)
                })
            
            return paragraphs
    except Exception as e:
        print(f"Error extracting text: {e}")
        return []

def create_redacted_docx(original_path, redactions, output_path):
    """Create a redacted DOCX file by modifying the XML content"""
    try:
        print(f"Creating redacted DOCX with {len(redactions)} redactions")
        
        with zipfile.ZipFile(original_path, 'r') as original_zip:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as new_zip:
                # Copy all files except document.xml
                for item in original_zip.infolist():
                    if item.filename != 'word/document.xml':
                        new_zip.writestr(item, original_zip.read(item.filename))
                
                # Process document.xml with redactions
                doc_xml = original_zip.read('word/document.xml').decode('utf-8')
                
                # Parse XML with proper namespace handling
                root = ET.fromstring(doc_xml)
                
                # Register namespace to preserve it
                ET.register_namespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
                ET.register_namespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
                
                # Define namespace
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                
                # Group redactions by paragraph for efficiency
                redactions_by_para = {}
                for redaction in redactions:
                    para_id = redaction.get('paragraphId', 0)
                    if para_id not in redactions_by_para:
                        redactions_by_para[para_id] = []
                    redactions_by_para[para_id].append(redaction)
                
                # Apply redactions
                paragraphs = root.findall('.//w:p', ns)
                
                for para_id, para_redactions in redactions_by_para.items():
                    if para_id < len(paragraphs):
                        para = paragraphs[para_id]
                        
                        # Get all text runs in this paragraph
                        runs = para.findall('.//w:r', ns)
                        
                        # Collect all text content and positions
                        full_text = ''
                        text_elements = []
                        
                        for run in runs:
                            for t_elem in run.findall('.//w:t', ns):
                                if t_elem.text:
                                    text_elements.append({
                                        'element': t_elem,
                                        'start': len(full_text),
                                        'end': len(full_text) + len(t_elem.text),
                                        'text': t_elem.text
                                    })
                                    full_text += t_elem.text
                        
                        # Sort redactions by start position (descending to avoid offset issues)
                        para_redactions.sort(key=lambda x: x.get('startPos', 0), reverse=True)
                        
                        # Apply redactions to the full text
                        redacted_text = full_text
                        for redaction in para_redactions:
                            start_pos = redaction.get('startPos', 0)
                            end_pos = redaction.get('endPos', 0)
                            
                            if 0 <= start_pos < len(redacted_text) and start_pos < end_pos <= len(redacted_text):
                                redaction_length = end_pos - start_pos
                                redaction_blocks = '█' * redaction_length
                                redacted_text = redacted_text[:start_pos] + redaction_blocks + redacted_text[end_pos:]
                        
                        # Clear all existing text elements
                        for text_info in text_elements:
                            text_info['element'].text = ''
                        
                        # Put all redacted text in the first text element
                        if text_elements:
                            text_elements[0]['element'].text = redacted_text
                        elif runs:
                            # If no text elements exist, create one
                            new_t = ET.SubElement(runs[0], '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')
                            new_t.text = redacted_text
                
                # Write modified document.xml with proper encoding
                new_xml = ET.tostring(root, encoding='unicode', xml_declaration=False)
                # Add XML declaration manually
                full_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + new_xml
                new_zip.writestr('word/document.xml', full_xml.encode('utf-8'))
        
        print("Redacted DOCX created successfully")
        return True
    except Exception as e:
        print(f"Error creating redacted DOCX: {e}")
        import traceback
        traceback.print_exc()
        return False

@redaction_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        # Create unique filename to avoid conflicts
        original_filename = secure_filename(file.filename)
        timestamp = str(int(time.time()))
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{timestamp}_{unique_id}_{original_filename}"
        
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        
        # Clean up any old redaction files for this session
        redaction_file = os.path.join(UPLOAD_FOLDER, f"{filename}_redactions.json")
        if os.path.exists(redaction_file):
            os.remove(redaction_file)
        
        # Extract text content from the document
        try:
            content = extract_text_from_docx(filepath)
            
            if not content:
                return jsonify({'error': 'Could not extract text from document'}), 500
            
            return jsonify({
                'success': True,
                'filename': filename,
                'original_filename': original_filename,
                'content': content
            })
        except Exception as e:
            return jsonify({'error': f'Error processing document: {str(e)}'}), 500
    
    return jsonify({'error': 'Invalid file type. Only .docx files are allowed.'}), 400

@redaction_bp.route('/redact', methods=['POST'])
def apply_redaction():
    data = request.get_json()
    filename = data.get('filename')
    redactions = data.get('redactions', [])
    
    print(f"Applying {len(redactions)} redactions to {filename}")
    
    if not filename:
        return jsonify({'error': 'No filename provided'}), 400
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Store redaction information with timestamp
        redaction_data = {
            'filename': filename,
            'redactions': redactions,
            'timestamp': time.time(),
            'redaction_count': len(redactions)
        }
        
        redaction_file = os.path.join(UPLOAD_FOLDER, f"{filename}_redactions.json")
        with open(redaction_file, 'w') as f:
            json.dump(redaction_data, f, indent=2)
        
        print(f"Saved {len(redactions)} redactions to {redaction_file}")
        
        return jsonify({
            'success': True, 
            'message': f'Applied {len(redactions)} redactions successfully',
            'redaction_count': len(redactions)
        })
    
    except Exception as e:
        print(f"Error in apply_redaction: {e}")
        return jsonify({'error': f'Error applying redactions: {str(e)}'}), 500

@redaction_bp.route('/download/docx/<filename>')
def download_redacted_docx(filename):
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    redaction_file = os.path.join(UPLOAD_FOLDER, f"{filename}_redactions.json")
    
    print(f"Download request for {filename}")
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'Original file not found'}), 404
    
    # Load redaction data
    redactions = []
    if os.path.exists(redaction_file):
        with open(redaction_file, 'r') as f:
            redaction_data = json.load(f)
            redactions = redaction_data.get('redactions', [])
        print(f"Loaded {len(redactions)} redactions from file")
    else:
        print("No redaction file found - downloading original")
    
    try:
        # Create unique output filename to avoid caching issues
        timestamp = str(int(time.time()))
        original_name = redaction_data.get('filename', filename) if redactions else filename
        if '_' in original_name and original_name.count('_') >= 2:
            # Extract original filename from our unique naming
            parts = original_name.split('_', 2)
            if len(parts) >= 3:
                original_name = parts[2]
        
        output_filename = f"redacted_{timestamp}_{original_name}"
        output_path = os.path.join(UPLOAD_FOLDER, output_filename)
        
        # Always create a fresh redacted version
        if redactions:
            success = create_redacted_docx(filepath, redactions, output_path)
            if not success:
                return jsonify({'error': 'Failed to create redacted DOCX'}), 500
        else:
            # If no redactions, copy original file
            import shutil
            shutil.copy2(filepath, output_path)
        
        # Verify the file was created
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"Successfully created file at {output_path}")
            
            # Clean up old files to prevent accumulation
            try:
                # Remove the redaction file after successful download
                if os.path.exists(redaction_file):
                    os.remove(redaction_file)
            except:
                pass  # Don't fail download if cleanup fails
            
            return send_file(output_path, as_attachment=True, download_name=f"redacted_{original_name}")
        else:
            return jsonify({'error': 'Failed to create download file'}), 500
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Error generating download: {str(e)}'}), 500

