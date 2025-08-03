from flask import Blueprint, request, jsonify, send_file, Response
from werkzeug.utils import secure_filename
import os
import tempfile
import json
import zipfile
import xml.etree.ElementTree as ET
import io
import re

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
    """Create a redacted DOCX file by modifying the XML content with detailed logging"""
    try:
        print(f"DEBUG: Starting redaction with {len(redactions)} redactions")
        
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
                for i, redaction in enumerate(redactions):
                    para_id = redaction.get('paragraphId', 0)
                    if para_id not in redactions_by_para:
                        redactions_by_para[para_id] = []
                    redactions_by_para[para_id].append(redaction)
                    print(f"DEBUG: Redaction {i+1}: Paragraph {para_id}, positions {redaction.get('startPos', 0)}-{redaction.get('endPos', 0)}")
                
                print(f"DEBUG: Redactions grouped by paragraph: {list(redactions_by_para.keys())}")
                
                # Apply redactions
                paragraphs = root.findall('.//w:p', ns)
                print(f"DEBUG: Found {len(paragraphs)} paragraphs in document")
                
                for para_id, para_redactions in redactions_by_para.items():
                    if para_id < len(paragraphs):
                        para = paragraphs[para_id]
                        print(f"DEBUG: Processing paragraph {para_id} with {len(para_redactions)} redactions")
                        
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
                        
                        print(f"DEBUG: Paragraph {para_id} original text: '{full_text}'")
                        
                        # Sort redactions by start position (descending to avoid offset issues)
                        para_redactions.sort(key=lambda x: x.get('startPos', 0), reverse=True)
                        
                        # Apply redactions to the full text
                        redacted_text = full_text
                        for j, redaction in enumerate(para_redactions):
                            start_pos = redaction.get('startPos', 0)
                            end_pos = redaction.get('endPos', 0)
                            
                            print(f"DEBUG: Applying redaction {j+1} in paragraph {para_id}: positions {start_pos}-{end_pos}")
                            
                            if 0 <= start_pos < len(redacted_text) and start_pos < end_pos <= len(redacted_text):
                                redaction_length = end_pos - start_pos
                                redaction_blocks = '█' * redaction_length
                                original_segment = redacted_text[start_pos:end_pos]
                                redacted_text = redacted_text[:start_pos] + redaction_blocks + redacted_text[end_pos:]
                                print(f"DEBUG: Redacted '{original_segment}' -> '{redaction_blocks}'")
                            else:
                                print(f"DEBUG: Invalid redaction positions {start_pos}-{end_pos} for text length {len(redacted_text)}")
                        
                        print(f"DEBUG: Paragraph {para_id} final text: '{redacted_text}'")
                        
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
                    else:
                        print(f"DEBUG: Paragraph {para_id} not found (document has {len(paragraphs)} paragraphs)")
                
                # Write modified document.xml with proper encoding
                new_xml = ET.tostring(root, encoding='unicode', xml_declaration=False)
                # Add XML declaration manually
                full_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + new_xml
                new_zip.writestr('word/document.xml', full_xml.encode('utf-8'))
        
        print("DEBUG: Redaction completed successfully")
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
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        
        # Extract text content from the document
        try:
            content = extract_text_from_docx(filepath)
            
            if not content:
                return jsonify({'error': 'Could not extract text from document'}), 500
            
            return jsonify({
                'success': True,
                'filename': filename,
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
    
    print(f"DEBUG: Received redaction request for {filename} with {len(redactions)} redactions")
    for i, redaction in enumerate(redactions):
        print(f"DEBUG: Redaction {i+1}: {redaction}")
    
    if not filename:
        return jsonify({'error': 'No filename provided'}), 400
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    try:
        # Store redaction information for later use
        redaction_data = {
            'filename': filename,
            'redactions': redactions
        }
        
        redaction_file = os.path.join(UPLOAD_FOLDER, f"{filename}_redactions.json")
        with open(redaction_file, 'w') as f:
            json.dump(redaction_data, f, indent=2)
        
        print(f"DEBUG: Saved {len(redactions)} redactions to {redaction_file}")
        
        return jsonify({
            'success': True, 
            'message': f'Applied {len(redactions)} redactions successfully'
        })
    
    except Exception as e:
        print(f"DEBUG: Error in apply_redaction: {e}")
        return jsonify({'error': f'Error applying redactions: {str(e)}'}), 500

@redaction_bp.route('/download/<format_type>/<filename>')
def download_redacted(format_type, filename):
    if format_type not in ['docx', 'pdf']:
        return jsonify({'error': 'Invalid format. Use docx or pdf.'}), 400
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    redaction_file = os.path.join(UPLOAD_FOLDER, f"{filename}_redactions.json")
    
    print(f"DEBUG: Download request for {filename} in {format_type} format")
    print(f"DEBUG: Looking for redaction file at {redaction_file}")
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'Original file not found'}), 404
    
    # Load redaction data
    redactions = []
    if os.path.exists(redaction_file):
        with open(redaction_file, 'r') as f:
            redaction_data = json.load(f)
            redactions = redaction_data.get('redactions', [])
        print(f"DEBUG: Loaded {len(redactions)} redactions from file")
    else:
        print("DEBUG: No redaction file found")
    
    try:
        if format_type == 'docx':
            return download_docx_debug(filepath, redactions, filename)
        else:
            return download_pdf_debug(filepath, redactions, filename)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Error generating {format_type}: {str(e)}'}), 500

def download_docx_debug(filepath, redactions, original_filename):
    output_filename = f"redacted_{original_filename}"
    output_path = os.path.join(UPLOAD_FOLDER, output_filename)
    
    print(f"DEBUG: Creating redacted DOCX with {len(redactions)} redactions")
    
    if create_redacted_docx(filepath, redactions, output_path):
        # Verify the redacted file was created and has content
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"DEBUG: Successfully created redacted file at {output_path}")
            return send_file(output_path, as_attachment=True, download_name=output_filename)
        else:
            return jsonify({'error': 'Failed to create redacted DOCX file'}), 500
    else:
        return jsonify({'error': 'Failed to process redactions in DOCX'}), 500

def download_pdf_debug(filepath, redactions, original_filename):
    # Extract text from original document
    content = extract_text_from_docx(filepath)
    
    # Apply redactions to text
    for redaction in redactions:
        paragraph_id = redaction.get('paragraphId')
        start_pos = redaction.get('startPos', 0)
        end_pos = redaction.get('endPos', 0)
        
        if paragraph_id < len(content):
            paragraph = content[paragraph_id]
            original_text = paragraph['text']
            
            if start_pos < len(original_text) and end_pos <= len(original_text):
                redacted_length = end_pos - start_pos
                redaction_blocks = '█' * redacted_length
                new_text = original_text[:start_pos] + redaction_blocks + original_text[end_pos:]
                paragraph['text'] = new_text
    
    # Create a text file with redacted content
    output_filename = f"redacted_{original_filename.replace('.docx', '.txt')}"
    output_path = os.path.join(UPLOAD_FOLDER, output_filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("REDACTED DOCUMENT\n")
        f.write("=" * 50 + "\n\n")
        
        for paragraph in content:
            if paragraph['text'].strip():
                f.write(paragraph['text'] + "\n\n")
    
    return send_file(output_path, as_attachment=True, download_name=output_filename)

