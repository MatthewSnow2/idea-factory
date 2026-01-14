import React, { useState } from 'react';
import { Plus, Loader } from 'lucide-react';

interface IdeaFormProps {
  onSuccess?: () => void;
}

export const IdeaForm: React.FC<IdeaFormProps> = ({ onSuccess }) => {
  const [rawText, setRawText] = useState('');
  const [context, setContext] = useState('');
  const [projectHint, setProjectHint] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const response = await fetch('http://localhost:3001/api/ideas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rawText,
          context: context || null,
          projectHint: projectHint || null
        })
      });

      if (!response.ok) {
        throw new Error('Failed to create idea');
      }

      const data = await response.json();
      setSuccess(`Idea created! ID: ${data.id}`);
      setRawText('');
      setContext('');
      setProjectHint('');
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow-md p-6 mb-6">
      <h2 className="text-2xl font-bold mb-4 text-gray-900">Submit New Idea</h2>

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Idea Description *
        </label>
        <textarea
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          placeholder="What's your idea? Be specific about what, why, and for whom..."
          required
          rows={4}
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Additional Context
        </label>
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          placeholder="Any background information or context that helps understand this idea?"
          rows={2}
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Project Hint
        </label>
        <input
          type="text"
          value={projectHint}
          onChange={(e) => setProjectHint(e.target.value)}
          placeholder="Related project or area (optional)"
          className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-md text-red-700">
          {error}
        </div>
      )}

      {success && (
        <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-md text-green-700">
          ✅ {success}
        </div>
      )}

      <button
        type="submit"
        disabled={isLoading}
        className="flex items-center gap-2 px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 transition-colors"
      >
        {isLoading ? (
          <>
            <Loader className="animate-spin" size={18} />
            Processing...
          </>
        ) : (
          <>
            <Plus size={18} />
            Submit Idea
          </>
        )}
      </button>
    </form>
  );
};
