import React, { useEffect, useState } from 'react';
import { Lightbulb, RefreshCw } from 'lucide-react';
import { IdeaForm } from './components/IdeaForm';
import { IdeaCard } from './components/IdeaCard';

interface Idea {
  id: string;
  raw_text: string;
  status: string;
  created_at: string;
  evaluation_score?: number;
  strategic_recommendation?: string;
  enrichment?: any;
  evaluation?: any;
}

export const App: React.FC = () => {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');

  const loadIdeas = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch('http://localhost:3001/api/ideas');
      if (!response.ok) throw new Error('Failed to load ideas');
      const data = await response.json();
      setIdeas(data.ideas || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadIdeas();
    // Reload every 30 seconds to show updates
    const interval = setInterval(loadIdeas, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleAnalyze = async (id: string) => {
    try {
      const response = await fetch(
        `http://localhost:3001/api/ideas/${id}/analyze`,
        { method: 'POST' }
      );
      if (!response.ok) throw new Error('Analysis failed');
      // Reload after a delay to get updated results
      setTimeout(loadIdeas, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const filteredIdeas =
    filter === 'all'
      ? ideas
      : ideas.filter((idea) => idea.status === filter);

  const statusCounts = {
    pending: ideas.filter((i) => i.status === 'pending').length,
    enriched: ideas.filter((i) => i.status === 'enriched').length,
    'evaluated-ready': ideas.filter((i) => i.status === 'evaluated-ready').length,
    deferred: ideas.filter((i) => i.status === 'deferred').length,
    research: ideas.filter((i) => i.status === 'research').length,
    archived: ideas.filter((i) => i.status === 'archived').length
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Lightbulb className="text-yellow-500" size={32} />
              <div>
                <h1 className="text-3xl font-bold text-gray-900">
                  Idea Factory
                </h1>
                <p className="text-sm text-gray-600">
                  Continuous innovation pipeline with AI-powered analysis
                </p>
              </div>
            </div>
            <button
              onClick={loadIdeas}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <RefreshCw size={18} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* Idea form */}
        <IdeaForm onSuccess={loadIdeas} />

        {/* Status overview */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-8">
          {[
            { status: 'pending', label: 'Pending', color: 'bg-gray-100' },
            { status: 'enriched', label: 'Enriched', color: 'bg-blue-100' },
            {
              status: 'evaluated-ready',
              label: 'Ready',
              color: 'bg-green-100'
            },
            { status: 'deferred', label: 'Deferred', color: 'bg-yellow-100' },
            { status: 'research', label: 'Research', color: 'bg-purple-100' },
            { status: 'archived', label: 'Archived', color: 'bg-red-100' }
          ].map(({ status, label, color }) => (
            <button
              key={status}
              onClick={() =>
                setFilter(
                  filter === status ? 'all' : (status as any)
                )
              }
              className={`p-3 rounded-lg text-center transition-all ${
                filter === status
                  ? `${color} ring-2 ring-offset-2 ring-gray-400`
                  : `${color} hover:ring-2 hover:ring-offset-2 hover:ring-gray-300`
              }`}
            >
              <div className="text-2xl font-bold text-gray-900">
                {statusCounts[status as keyof typeof statusCounts]}
              </div>
              <div className="text-xs text-gray-600 mt-1">{label}</div>
            </button>
          ))}
        </div>

        {/* Ideas list */}
        {isLoading ? (
          <div className="text-center py-12">
            <div className="inline-block">
              <RefreshCw className="animate-spin text-blue-600" size={32} />
            </div>
            <p className="mt-4 text-gray-600">Loading ideas...</p>
          </div>
        ) : error ? (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            Error: {error}
          </div>
        ) : filteredIdeas.length === 0 ? (
          <div className="text-center py-12 text-gray-600">
            No ideas yet. Create one to get started!
          </div>
        ) : (
          <div>
            <h2 className="text-xl font-bold text-gray-900 mb-4">
              {filter === 'all'
                ? `All Ideas (${filteredIdeas.length})`
                : `${filter.charAt(0).toUpperCase() + filter.slice(1)} (${filteredIdeas.length})`}
            </h2>
            <div className="space-y-2">
              {filteredIdeas.map((idea) => (
                <IdeaCard
                  key={idea.id}
                  idea={idea}
                  enrichment={idea.enrichment}
                  evaluation={idea.evaluation}
                  onAnalyze={handleAnalyze}
                />
              ))}
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="mt-12 border-t border-gray-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
          <p className="text-sm text-gray-600 text-center">
            Phase 1: Manual submission → Enrichment → Evaluation
          </p>
        </div>
      </footer>
    </div>
  );
};
