from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
import os
import tempfile
import json
import zipfile
import xml.etree.ElementTree as ET
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph
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
                
                if text_content.strip():
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
        with zipfile.ZipFile(original_path, 'r') as original_zip:
            with zipfile.ZipFile(output_path, 'w') as new_zip:
                # Copy all files except document.xml
                for item in original_zip.infolist():
                    if item.filename != 'word/document.xml':
                        new_zip.writestr(item, original_zip.read(item.filename))
                
                # Process document.xml with redactions
                doc_xml = original_zip.read('word/document.xml')
                root = ET.fromstring(doc_xml)
                
                # Define namespace
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                
                # Apply redactions
                paragraphs = root.findall('.//w:p', ns)
                for redaction in redactions:
                    para_id = redaction.get('paragraphId', 0)
                    start_pos = redaction.get('startPos', 0)
                    end_pos = redaction.get('endPos', 0)
                    
                    if para_id < len(paragraphs):
                        para = paragraphs[para_id]
                        
                        # Get all text elements in this paragraph
                        text_elements = para.findall('.//w:t', ns)
                        
                        # Reconstruct paragraph text and apply redaction
                        full_text = ''
                        for t_elem in text_elements:
                            if t_elem.text:
                                full_text += t_elem.text
                        
                        if start_pos < len(full_text) and end_pos <= len(full_text):
                            redaction_length = end_pos - start_pos
                            redacted_text = full_text[:start_pos] + '█' * redaction_length + full_text[end_pos:]
                            
                            # Clear existing text elements
                            for t_elem in text_elements:
                                t_elem.text = ''
                            
                            # Set redacted text to first text element
                            if text_elements:
                                text_elements[0].text = redacted_text
                
                # Write modified document.xml
                new_xml = ET.tostring(root, encoding='unicode')
                new_zip.writestr('word/document.xml', new_xml)
        
        return True
    except Exception as e:
        print(f"Error creating redacted DOCX: {e}")
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
            json.dump(redaction_data, f)
        
        return jsonify({'success': True, 'message': 'Redactions applied successfully'})
    
    except Exception as e:
        return jsonify({'error': f'Error applying redactions: {str(e)}'}), 500

@redaction_bp.route('/download/<format_type>/<filename>')
def download_redacted(format_type, filename):
    if format_type not in ['docx', 'pdf']:
        return jsonify({'error': 'Invalid format. Use docx or pdf.'}), 400
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    redaction_file = os.path.join(UPLOAD_FOLDER, f"{filename}_redactions.json")
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'Original file not found'}), 404
    
    # Load redaction data
    redactions = []
    if os.path.exists(redaction_file):
        with open(redaction_file, 'r') as f:
            redaction_data = json.load(f)
            redactions = redaction_data.get('redactions', [])
    
    try:
        if format_type == 'docx':
            return download_docx_simple(filepath, redactions, filename)
        else:
            return download_pdf_simple(filepath, redactions, filename)
    
    except Exception as e:
        return jsonify({'error': f'Error generating {format_type}: {str(e)}'}), 500

def download_docx_simple(filepath, redactions, original_filename):
    output_filename = f"redacted_{original_filename}"
    output_path = os.path.join(UPLOAD_FOLDER, output_filename)
    
    if create_redacted_docx(filepath, redactions, output_path):
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    else:
        return jsonify({'error': 'Failed to create redacted DOCX'}), 500

def download_pdf_simple(filepath, redactions, original_filename):
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
    
    # Create PDF
    output_filename = f"redacted_{original_filename.replace('.docx', '.pdf')}"
    output_path = os.path.join(UPLOAD_FOLDER, output_filename)
    
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    for paragraph in content:
        if paragraph['text'].strip():
            para = Paragraph(paragraph['text'], styles['Normal'])
            story.append(para)
    
    doc.build(story)
    
    return send_file(output_path, as_attachment=True, download_name=output_filename)

