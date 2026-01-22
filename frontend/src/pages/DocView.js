import { useState, useEffect } from 'react';
import axios from 'axios';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Separator } from '../components/ui/separator';
import { Loader2, ArrowLeft, ExternalLink, CheckCircle, AlertCircle, Clock } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const DocView = () => {
  const { docId } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [freshness, setFreshness] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchDoc = async () => {
    try {
      const docResponse = await axios.get(`${API}/scopedocs/${docId}`);
      setDoc(docResponse.data);
      
      const freshnessResponse = await axios.get(`${API}/freshness/${docId}`);
      setFreshness(freshnessResponse.data);
    } catch (error) {
      console.error('Error fetching doc:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDoc();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId]);

  const getFreshnessColor = (level) => {
    switch (level) {
      case 'fresh': return 'text-green-500';
      case 'stale': return 'text-yellow-500';
      case 'outdated': return 'text-red-500';
      default: return 'text-gray-500';
    }
  };

  const getFreshnessIcon = (level) => {
    switch (level) {
      case 'fresh': return CheckCircle;
      case 'stale': return Clock;
      case 'outdated': return AlertCircle;
      default: return CheckCircle;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="text-center py-12">
        <h2 className="text-2xl font-bold">Document not found</h2>
        <Button onClick={() => navigate('/docs')} className="mt-4">
          Back to Docs
        </Button>
      </div>
    );
  }

  const FreshnessIcon = getFreshnessIcon(doc.freshness_level);

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={() => navigate('/docs')} data-testid="back-to-docs-btn">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Docs
        </Button>
        <Badge 
          variant={doc.freshness_level === 'fresh' ? 'default' : 'destructive'}
          className="capitalize"
          data-testid="doc-freshness-badge"
        >
          <FreshnessIcon className={`h-3 w-3 mr-1 ${getFreshnessColor(doc.freshness_level)}`} />
          {doc.freshness_level}
        </Badge>
      </div>

      <div>
        <h1 className="text-4xl font-bold" data-testid="doc-title">{doc.project_name}</h1>
        <p className="text-muted-foreground mt-2">
          Last verified: {new Date(doc.last_verified_at).toLocaleDateString()}
        </p>
      </div>

      {freshness && freshness.needs_update && (
        <Card className="border-yellow-500 bg-yellow-50 dark:bg-yellow-950" data-testid="freshness-warning">
          <CardHeader>
            <CardTitle className="text-yellow-700 dark:text-yellow-300">
              <AlertCircle className="h-5 w-5 inline mr-2" />
              Documentation May Be Outdated
            </CardTitle>
            <CardDescription className="text-yellow-600 dark:text-yellow-400">
              Freshness score: {(freshness.freshness_score * 100).toFixed(0)}%
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-yellow-700 dark:text-yellow-300">
            {freshness.trigger_events} events detected since last verification.
            This documentation may need to be updated.
          </CardContent>
        </Card>
      )}

      <Card data-testid="doc-content">
        <CardHeader>
          <CardTitle>Documentation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {Object.entries(doc.sections || {}).map(([sectionKey, sectionContent]) => (
            <div key={sectionKey} data-testid={`doc-section-${sectionKey}`}>
              <h2 className="text-2xl font-semibold capitalize mb-3">
                {sectionKey.replace(/_/g, ' ')}
              </h2>
              <div className="prose dark:prose-invert max-w-none whitespace-pre-wrap">
                {sectionContent || 'No content yet'}
              </div>
              {sectionKey !== Object.keys(doc.sections)[Object.keys(doc.sections).length - 1] && (
                <Separator className="mt-6" />
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      {doc.evidence_links && doc.evidence_links.length > 0 && (
        <Card data-testid="evidence-links-card">
          <CardHeader>
            <CardTitle>Evidence Links</CardTitle>
            <CardDescription>
              Source artifacts used to generate this documentation
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {doc.evidence_links.map((link, index) => (
                <div 
                  key={index} 
                  className="flex items-center justify-between p-3 border rounded-lg hover:bg-accent transition-colors"
                  data-testid={`evidence-link-${index}`}
                >
                  <div>
                    <Badge variant="outline" className="mb-1">{link.type}</Badge>
                    <p className="text-sm font-medium">{link.title}</p>
                    <p className="text-xs text-muted-foreground">{link.id}</p>
                  </div>
                  <Button variant="ghost" size="sm" asChild>
                    <a href={link.url} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default DocView;