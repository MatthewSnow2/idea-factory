import React, { useState } from 'react';
import { Zap, ChevronDown, Loader } from 'lucide-react';

interface IdeaCardProps {
  idea: {
    id: string;
    raw_text: string;
    status: string;
    created_at: string;
    evaluation_score?: number;
    strategic_recommendation?: string;
  };
  enrichment?: any;
  evaluation?: any;
  onAnalyze?: (id: string) => Promise<void>;
}

export const IdeaCard: React.FC<IdeaCardProps> = ({
  idea,
  enrichment,
  evaluation,
  onAnalyze
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-gray-100 text-gray-800',
      enriched: 'bg-blue-100 text-blue-800',
      'evaluated-ready': 'bg-green-100 text-green-800',
      deferred: 'bg-yellow-100 text-yellow-800',
      research: 'bg-purple-100 text-purple-800',
      archived: 'bg-red-100 text-red-800'
    };
    return colors[status] || colors.pending;
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-600';
    if (score >= 60) return 'text-blue-600';
    if (score >= 40) return 'text-yellow-600';
    return 'text-red-600';
  };

  const handleAnalyze = async () => {
    if (onAnalyze) {
      setIsAnalyzing(true);
      try {
        await onAnalyze(idea.id);
      } finally {
        setIsAnalyzing(false);
      }
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-md hover:shadow-lg transition-shadow mb-4">
      <div className="p-4">
        {/* Header with title and status */}
        <div className="flex items-start justify-between mb-2">
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-gray-900 mb-1 line-clamp-2">
              {idea.raw_text.substring(0, 80)}...
            </h3>
            <p className="text-xs text-gray-500">
              Created: {new Date(idea.created_at).toLocaleDateString()}
            </p>
          </div>
          <span
            className={`ml-2 px-3 py-1 rounded-full text-sm font-medium whitespace-nowrap ${
              getStatusColor(idea.status)
            }`}
          >
            {idea.status}
          </span>
        </div>

        {/* Evaluation score if available */}
        {evaluation && (
          <div className="mb-3 pb-3 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Evaluation Score</span>
              <span className={`text-xl font-bold ${getScoreColor(evaluation.evaluationScore)}`}>
                {evaluation.evaluationScore}/100
              </span>
            </div>
            {evaluation.recommendation && (
              <p className="text-xs text-gray-600 mt-1">
                Recommendation: <strong>{evaluation.recommendation}</strong>
              </p>
            )}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleAnalyze}
            disabled={isAnalyzing || idea.status !== 'pending'}
            className="flex items-center gap-1 px-3 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:bg-gray-400 transition-colors"
          >
            {isAnalyzing ? (
              <>
                <Loader size={16} className="animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Zap size={16} />
                Analyze
              </>
            )}
          </button>

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="ml-auto p-2 text-gray-600 hover:bg-gray-100 rounded"
          >
            <ChevronDown
              size={20}
              className={`transition-transform ${
                isExpanded ? 'rotate-180' : ''
              }`}
            />
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className="bg-gray-50 border-t border-gray-200 p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Enrichment data */}
            {enrichment && (
              <div>
                <h4 className="font-semibold text-sm text-gray-700 mb-2">
                  Enrichment Analysis
                </h4>
                <dl className="space-y-1 text-sm">
                  <div>
                    <dt className="text-gray-600">Category:</dt>
                    <dd className="text-gray-900">{enrichment.category}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-600">Complexity:</dt>
                    <dd className="text-gray-900">
                      {(enrichment.complexityScore * 100).toFixed(0)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-gray-600">Stack Fit:</dt>
                    <dd className="text-gray-900">
                      {enrichment.technicalFeasibility.stackFit}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-gray-600">Est. Hours:</dt>
                    <dd className="text-gray-900">
                      {enrichment.resourceEstimate.estimatedHours}
                    </dd>
                  </div>
                </dl>
              </div>
            )}

            {/* Evaluation data */}
            {evaluation && (
              <div>
                <h4 className="font-semibold text-sm text-gray-700 mb-2">
                  Strategic Evaluation
                </h4>
                <dl className="space-y-1 text-sm">
                  <div>
                    <dt className="text-gray-600">Disruption Score:</dt>
                    <dd className="text-gray-900">
                      {(evaluation.disruptionScore * 100).toFixed(0)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-gray-600">Capabilities Fit:</dt>
                    <dd className="text-gray-900">
                      {evaluation.capabilitiesFit}
                    </dd>
                  </div>
                  {evaluation.caseStudyMatches?.length > 0 && (
                    <div>
                      <dt className="text-gray-600">Case Studies:</dt>
                      <dd className="text-gray-900">
                        {evaluation.caseStudyMatches.join(', ')}
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            )}
          </div>

          {/* Full JTBD analysis */}
          {evaluation?.jtbdAnalysis && (
            <div className="mt-4 p-3 bg-blue-50 rounded border border-blue-200">
              <h5 className="font-semibold text-sm text-blue-900 mb-2">
                Jobs-to-be-Done Analysis
              </h5>
              <p className="text-sm text-blue-800">{evaluation.jtbdAnalysis}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
