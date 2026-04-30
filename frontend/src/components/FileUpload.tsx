import React, { useRef, useState } from "react";
import { UploadCloud, CheckCircle, FileText, Loader2 } from "lucide-react";

interface FileUploadProps {
  onUpload: (file: File) => Promise<void>;
  isLoading: boolean;
}

export const FileUpload: React.FC<FileUploadProps> = ({ onUpload, isLoading }) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  const handleDrag = function(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = function(e: React.DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(e.dataTransfer.files[0]);
    }
  };

  const handleChange = function(e: React.ChangeEvent<HTMLInputElement>) {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFiles(e.target.files[0]);
    }
  };

  const handleFiles = (file: File) => {
    if (file.type !== "application/pdf") {
      throw new Error("Invalid file type. Please upload a PDF.");
    }
    setFileName(file.name);
    onUpload(file);
  };

  const onButtonClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div 
      className={`relative p-6 border border-dashed rounded-2xl transition-all duration-200 ease-in-out text-center cursor-pointer flex flex-col justify-center items-center h-36 shadow-sm hover:shadow-md ${
        dragActive
          ? "border-blue-300 bg-blue-50 dark:border-blue-500/40 dark:bg-blue-500/10"
          : "border-slate-200 hover:border-slate-300 bg-white/70 hover:bg-slate-50 dark:border-slate-800/60 dark:hover:border-slate-700 dark:bg-slate-950/30 dark:hover:bg-slate-900/40"
      } ${isLoading ? "pointer-events-none opacity-80 backdrop-blur-sm max-h-36" : ""}`}
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
      onClick={onButtonClick}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple={false}
        accept="application/pdf"
        onChange={handleChange}
        className="hidden"
      />
      
      {isLoading ? (
        <div className="flex flex-col items-center justify-center text-slate-600 dark:text-slate-300 animate-fade-in space-y-3">
          <Loader2 className="w-8 h-8 animate-spin" />
          <p className="text-[10px] uppercase tracking-widest font-semibold">Uploading...</p>
        </div>
      ) : fileName ? (
        <div className="flex flex-col items-center justify-center text-slate-700 dark:text-slate-200 animate-fade-in space-y-2">
          <CheckCircle className="w-7 h-7 text-blue-600 dark:text-blue-300" />
          <div className="flex items-center text-xs font-semibold text-slate-700 dark:text-slate-200 bg-white/80 dark:bg-slate-900/40 px-3 py-1 rounded border border-slate-100/50 dark:border-slate-800/60">
            <FileText className="w-3.5 h-3.5 mr-2 text-slate-500 dark:text-slate-300" />
            <span className="truncate max-w-[150px]">{fileName}</span>
          </div>
          <p className="text-[9px] text-slate-500 dark:text-slate-400 uppercase tracking-widest mt-1">Ready</p>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center text-slate-500 dark:text-slate-400 animate-fade-in">
          <div className="p-3 bg-slate-50 dark:bg-slate-900/40 rounded-full mb-3 transition-colors">
            <UploadCloud className="w-6 h-6 text-slate-500 dark:text-slate-300 transition-colors" />
          </div>
          <p className="text-xs font-semibold tracking-wide text-slate-700 dark:text-slate-200">Click to upload, or drag a PDF</p>
          <p className="text-[9px] uppercase tracking-widest text-slate-500 dark:text-slate-500 mt-2 font-semibold select-none text-center">
            PDF only
          </p>
        </div>
      )}
    </div>
  );
};
