import { useState, useRef } from 'react'
import { Button } from '@/components/ui/button.jsx'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card.jsx'
import { Upload, Download, FileText, Eye, EyeOff, AlertCircle, CheckCircle, Trash2, Plus } from 'lucide-react'
import './App.css'

function App() {
  const [file, setFile] = useState(null)
  const [documentContent, setDocumentContent] = useState([])
  const [redactions, setRedactions] = useState([])
  const [isUploading, setIsUploading] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [selectedText, setSelectedText] = useState(null)
  const [filename, setFilename] = useState('')
  const [originalFilename, setOriginalFilename] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [uploadSuccess, setUploadSuccess] = useState(false)
  const [pendingRedactions, setPendingRedactions] = useState([])
  const fileInputRef = useRef(null)

  const handleFileUpload = async (event) => {
    const selectedFile = event.target.files[0]
    if (!selectedFile) return

    setUploadError('')
    setUploadSuccess(false)

    if (!selectedFile.name.endsWith('.docx')) {
      setUploadError('Please select a .docx file only')
      return
    }

    setFile(selectedFile)
    setIsUploading(true)

    const formData = new FormData()
    formData.append('file', selectedFile)

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      })

      const result = await response.json()
      
      if (result.success) {
        setDocumentContent(result.content)
        setFilename(result.filename)
        setOriginalFilename(result.original_filename || result.filename)
        setRedactions([])
        setPendingRedactions([])
        setUploadSuccess(true)
        setUploadError('')
      } else {
        setUploadError('Error uploading file: ' + result.error)
        setUploadSuccess(false)
      }
    } catch (error) {
      setUploadError('Error uploading file: ' + error.message)
      setUploadSuccess(false)
    } finally {
      setIsUploading(false)
    }
  }

  const handleTextSelection = (paragraphId, text) => {
    const selection = window.getSelection()
    if (selection.toString().length > 0) {
      const range = selection.getRangeAt(0)
      const startOffset = range.startOffset
      const endOffset = range.endOffset
      
      setSelectedText({
        paragraphId,
        text: selection.toString(),
        startPos: startOffset,
        endPos: endOffset
      })
    } else {
      setSelectedText(null)
    }
  }

  const addToPendingRedactions = () => {
    if (!selectedText) return

    // Check if this text is already in pending redactions
    const existingRedaction = pendingRedactions.find(r => 
      r.paragraphId === selectedText.paragraphId &&
      r.startPos === selectedText.startPos &&
      r.endPos === selectedText.endPos
    )

    if (existingRedaction) {
      alert('This text is already queued for redaction!')
      return
    }

    const newRedaction = {
      id: Date.now(),
      paragraphId: selectedText.paragraphId,
      startPos: selectedText.startPos,
      endPos: selectedText.endPos,
      text: selectedText.text
    }

    setPendingRedactions([...pendingRedactions, newRedaction])
    setSelectedText(null)
    
    // Clear selection
    window.getSelection().removeAllRanges()
  }

  const removePendingRedaction = (redactionId) => {
    setPendingRedactions(pendingRedactions.filter(r => r.id !== redactionId))
  }

  const applyAllRedactions = async () => {
    if (pendingRedactions.length === 0) {
      alert('No redactions to apply!')
      return
    }

    try {
      // Apply all pending redactions
      const allRedactions = [...redactions, ...pendingRedactions]
      setRedactions(allRedactions)
      setPendingRedactions([])

      // Send to backend
      const response = await fetch('/api/redact', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          filename: filename,
          redactions: allRedactions
        }),
      })

      const result = await response.json()
      if (!result.success) {
        throw new Error(result.error || 'Failed to apply redactions')
      }

      console.log(`Applied ${result.redaction_count || allRedactions.length} redactions successfully`)

    } catch (error) {
      alert('Error applying redactions: ' + error.message)
    }
  }

  const clearAllRedactions = () => {
    if (window.confirm('Are you sure you want to clear all redactions?')) {
      setRedactions([])
      setPendingRedactions([])
    }
  }

  const getRedactedText = (originalText, paragraphId) => {
    let redactedText = originalText
    const allRedactions = [...redactions, ...pendingRedactions]
    const paragraphRedactions = allRedactions.filter(r => r.paragraphId === paragraphId)
    
    // Sort redactions by start position in descending order to avoid offset issues
    paragraphRedactions.sort((a, b) => b.startPos - a.startPos)
    
    paragraphRedactions.forEach(redaction => {
      const redactionBlocks = '█'.repeat(redaction.endPos - redaction.startPos)
      redactedText = redactedText.substring(0, redaction.startPos) + 
                   redactionBlocks + 
                   redactedText.substring(redaction.endPos)
    })
    
    return redactedText
  }

  const downloadFile = async () => {
    if (!filename) return

    setIsDownloading(true)

    try {
      // Make sure all redactions are applied first
      if (pendingRedactions.length > 0) {
        await applyAllRedactions()
      }

      // Download the DOCX file with current timestamp to avoid caching
      const timestamp = Date.now()
      const downloadUrl = `/api/download/docx/${filename}?t=${timestamp}`
      
      const response = await fetch(downloadUrl)
      
      if (!response.ok) {
        throw new Error('Failed to download file')
      }

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `redacted_${originalFilename}`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
      
      console.log('Download completed successfully')
      
    } catch (error) {
      alert('Error downloading file: ' + error.message)
    } finally {
      setIsDownloading(false)
    }
  }

  const resetTool = () => {
    setFile(null)
    setDocumentContent([])
    setRedactions([])
    setPendingRedactions([])
    setSelectedText(null)
    setFilename('')
    setOriginalFilename('')
    setUploadError('')
    setUploadSuccess(false)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-gray-100 py-8 px-4">
      <div className="max-w-7xl mx-auto">
        <div className="mb-12 text-center">
          <h1 className="text-5xl font-bold text-gray-800 mb-4 tracking-tight">Document Redaction Tool</h1>
          <p className="text-gray-600 text-xl max-w-3xl mx-auto leading-relaxed">Upload a Word document, redact sensitive content, and download the redacted version securely.</p>
        </div>

        {/* File Upload Section */}
        <Card className="mb-8 shadow-xl border-0">
          <CardHeader className="bg-gradient-to-r from-blue-600 to-indigo-700 text-white rounded-t-xl">
            <CardTitle className="flex items-center gap-3 text-xl">
              <Upload className="h-7 w-7" />
              Step 1: Upload Document
            </CardTitle>
            <CardDescription className="text-blue-100 text-base">
              Select a .docx file to begin the redaction process (Max size: 16 MB)
            </CardDescription>
          </CardHeader>
          <CardContent className="p-8 bg-white">
            <div className="space-y-6">
              <div className="flex items-center gap-4">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".docx"
                  onChange={handleFileUpload}
                  className="file:mr-4 file:py-3 file:px-8 file:rounded-full file:border-0 file:text-base file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 file:cursor-pointer cursor-pointer text-gray-600"
                  disabled={isUploading}
                />
                {isUploading && (
                  <div className="flex items-center gap-3 text-blue-600">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                    <span className="text-base font-medium">Uploading and processing...</span>
                  </div>
                )}
              </div>
              
              {uploadError && (
                <div className="flex items-center gap-3 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700">
                  <AlertCircle className="h-5 w-5" />
                  <span className="text-base">{uploadError}</span>
                </div>
              )}

              {uploadSuccess && (
                <div className="flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-xl text-green-700">
                  <CheckCircle className="h-5 w-5" />
                  <span className="text-base">Document uploaded successfully! You can now view and redact content below.</span>
                </div>
              )}

              {file && (
                <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                  <div className="flex items-center gap-3">
                    <FileText className="h-5 w-5 text-gray-500" />
                    <span className="text-base font-medium text-gray-700">{file.name}</span>
                    <span className="text-sm text-gray-500">({(file.size / 1024).toFixed(1)} KB)</span>
                  </div>
                  <Button onClick={resetTool} variant="outline" size="sm" className="text-base">
                    Upload Different File
                  </Button>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Document Viewer and Redaction Section */}
        {documentContent.length > 0 && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
            <div className="xl:col-span-2">
              <Card className="shadow-xl border-0">
                <CardHeader className="bg-gradient-to-r from-green-600 to-emerald-700 text-white rounded-t-xl">
                  <CardTitle className="flex items-center gap-3 text-xl">
                    <FileText className="h-7 w-7" />
                    Step 2: Document Viewer & Redaction
                  </CardTitle>
                  <CardDescription className="text-green-100 text-base">
                    Select text and add to redaction queue. Apply all redactions at once.
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-8 bg-white">
                  <div className="bg-white border-2 border-gray-200 rounded-xl p-8 max-h-96 overflow-y-auto shadow-inner">
                    {documentContent.map((paragraph, index) => (
                      <p
                        key={index}
                        className="mb-6 leading-relaxed cursor-text select-text hover:bg-yellow-50 p-3 rounded-lg transition-colors text-gray-800"
                        onMouseUp={() => handleTextSelection(index, paragraph.text)}
                        style={{ fontFamily: 'Inter, system-ui, sans-serif', fontSize: '17px', lineHeight: '1.7' }}
                      >
                        {getRedactedText(paragraph.text, index)}
                      </p>
                    ))}
                  </div>
                  
                  {selectedText && (
                    <div className="mt-6 p-5 bg-yellow-50 border border-yellow-200 rounded-xl">
                      <p className="text-base font-semibold text-yellow-900 mb-3">Selected Text:</p>
                      <p className="text-base text-yellow-700 mb-4 italic">"{selectedText.text}"</p>
                      <Button onClick={addToPendingRedactions} className="bg-yellow-600 hover:bg-yellow-700 text-base px-6 py-2">
                        <Plus className="h-5 w-5 mr-2" />
                        Add to Redaction Queue
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            <div className="space-y-8">
              {/* Redaction Queue */}
              <Card className="shadow-xl border-0">
                <CardHeader className="bg-gradient-to-r from-purple-600 to-violet-700 text-white rounded-t-xl">
                  <CardTitle className="flex items-center gap-3 text-xl">
                    <Eye className="h-6 w-6" />
                    Redaction Queue
                  </CardTitle>
                  <CardDescription className="text-purple-100 text-base">
                    Manage your redactions before applying
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-6 space-y-5 bg-white">
                  <div className="flex items-center justify-between">
                    <span className="text-base font-semibold text-gray-700">Pending Redactions:</span>
                    <span className="text-2xl font-bold text-purple-600">{pendingRedactions.length}</span>
                  </div>

                  {pendingRedactions.length > 0 && (
                    <div className="space-y-3">
                      <div className="max-h-32 overflow-y-auto space-y-2">
                        {pendingRedactions.map((redaction) => (
                          <div key={redaction.id} className="flex items-center justify-between p-3 bg-yellow-50 rounded-lg text-sm border border-yellow-200">
                            <span className="truncate flex-1 text-gray-700">"{redaction.text.substring(0, 30)}..."</span>
                            <Button 
                              onClick={() => removePendingRedaction(redaction.id)}
                              variant="ghost" 
                              size="sm"
                              className="h-7 w-7 p-0 text-red-500 hover:text-red-700"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        ))}
                      </div>
                      <Button 
                        onClick={applyAllRedactions}
                        className="w-full bg-purple-600 hover:bg-purple-700 text-base py-3"
                      >
                        <EyeOff className="h-5 w-5 mr-2" />
                        Apply All Redactions ({pendingRedactions.length})
                      </Button>
                    </div>
                  )}

                  <div className="flex items-center justify-between pt-3 border-t">
                    <span className="text-base font-semibold text-gray-700">Applied Redactions:</span>
                    <span className="text-2xl font-bold text-green-600">{redactions.length}</span>
                  </div>

                  {(redactions.length > 0 || pendingRedactions.length > 0) && (
                    <Button 
                      onClick={clearAllRedactions}
                      variant="outline" 
                      className="w-full text-red-600 hover:text-red-700 text-base py-3"
                    >
                      <Trash2 className="h-5 w-5 mr-2" />
                      Clear All Redactions
                    </Button>
                  )}

                  <div className="text-sm text-gray-500 p-4 bg-gray-50 rounded-lg">
                    <strong>How to redact:</strong> Select text in the document, add to queue, then apply all redactions at once for better performance.
                  </div>
                </CardContent>
              </Card>

              {/* Download Section */}
              <Card className="shadow-xl border-0">
                <CardHeader className="bg-gradient-to-r from-orange-600 to-red-700 text-white rounded-t-xl">
                  <CardTitle className="flex items-center gap-3 text-xl">
                    <Download className="h-7 w-7" />
                    Step 3: Download Redacted Document
                  </CardTitle>
                  <CardDescription className="text-orange-100 text-base">
                    Download your document with all redactions applied
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-6 space-y-5 bg-white">
                  {pendingRedactions.length > 0 && (
                    <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-xl text-yellow-700 text-base">
                      <AlertCircle className="h-5 w-5 inline mr-2" />
                      You have {pendingRedactions.length} pending redactions. They will be applied automatically when you download.
                    </div>
                  )}

                  <Button 
                    onClick={downloadFile}
                    disabled={!filename || isDownloading}
                    className="w-full bg-blue-600 hover:bg-blue-700 text-base py-4"
                    size="lg"
                  >
                    {isDownloading ? (
                      <div className="flex items-center gap-3">
                        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                        Processing & Downloading...
                      </div>
                    ) : (
                      <>
                        <Download className="h-5 w-5 mr-2" />
                        Download Redacted DOCX
                      </>
                    )}
                  </Button>

                  <div className="text-sm text-gray-500 p-4 bg-gray-50 rounded-lg">
                    <strong>Security Note:</strong> Your documents are processed securely and are automatically deleted from our servers after download.
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        )}

        {/* Instructions */}
        {documentContent.length === 0 && !file && (
          <Card className="shadow-xl border-0 mb-8">
            <CardHeader className="bg-white rounded-t-xl">
              <CardTitle className="text-2xl text-gray-800">How to Use This Tool</CardTitle>
            </CardHeader>
            <CardContent className="bg-white p-8">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                <div className="text-center">
                  <div className="bg-blue-100 rounded-full w-20 h-20 flex items-center justify-center mx-auto mb-6">
                    <Upload className="h-10 w-10 text-blue-600" />
                  </div>
                  <h3 className="font-semibold mb-3 text-lg text-gray-800">1. Upload Document</h3>
                  <p className="text-base text-gray-600 leading-relaxed">Select and upload your .docx file to begin the redaction process.</p>
                </div>
                <div className="text-center">
                  <div className="bg-green-100 rounded-full w-20 h-20 flex items-center justify-center mx-auto mb-6">
                    <EyeOff className="h-10 w-10 text-green-600" />
                  </div>
                  <h3 className="font-semibold mb-3 text-lg text-gray-800">2. Queue & Apply Redactions</h3>
                  <p className="text-base text-gray-600 leading-relaxed">Select multiple text sections, add to queue, then apply all redactions at once.</p>
                </div>
                <div className="text-center">
                  <div className="bg-orange-100 rounded-full w-20 h-20 flex items-center justify-center mx-auto mb-6">
                    <Download className="h-10 w-10 text-orange-600" />
                  </div>
                  <h3 className="font-semibold mb-3 text-lg text-gray-800">3. Download</h3>
                  <p className="text-base text-gray-600 leading-relaxed">Download your redacted document as DOCX format with all changes applied.</p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

export default App

