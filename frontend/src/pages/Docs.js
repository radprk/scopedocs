import { useState, useEffect } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Loader2, FileText, CheckCircle, AlertCircle, Clock } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Docs = () => {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchDocs = async () => {
    try {
      const response = await axios.get(`${API}/scopedocs`);
      setDocs(response.data || []);
    } catch (error) {
      console.error('Error fetching docs:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, []);

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
      default: return FileText;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-4xl font-bold" data-testid="docs-title">ScopeDocs</h1>
        <p className="text-muted-foreground mt-2">Living documentation for your projects</p>
      </div>

      {docs.length === 0 ? (
        <Card className="border-dashed" data-testid="no-docs-card">
          <CardHeader>
            <CardTitle>No Documentation Yet</CardTitle>
            <CardDescription>
              Go to Projects to generate documentation from your Linear projects
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => navigate('/projects')} data-testid="go-to-projects-btn">
              View Projects
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-6">
          {docs.map((doc) => {
            const FreshnessIcon = getFreshnessIcon(doc.freshness_level);
            return (
              <Card 
                key={doc.id} 
                className="hover:shadow-lg transition-shadow cursor-pointer"
                onClick={() => navigate(`/docs/${doc.id}`)}
                data-testid={`doc-card-${doc.id}`}
              >
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="space-y-1">
                      <CardTitle className="text-xl">{doc.project_name}</CardTitle>
                      <CardDescription>
                        Last verified: {new Date(doc.last_verified_at).toLocaleDateString()}
                      </CardDescription>
                    </div>
                    <Badge 
                      variant={doc.freshness_level === 'fresh' ? 'default' : 'destructive'}
                      className="capitalize"
                      data-testid={`freshness-badge-${doc.id}`}
                    >
                      <FreshnessIcon className={`h-3 w-3 mr-1 ${getFreshnessColor(doc.freshness_level)}`} />
                      {doc.freshness_level}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    <div className="text-sm text-muted-foreground">
                      Sections: {Object.keys(doc.sections || {}).length}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Evidence links: {doc.evidence_links?.length || 0}
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default Docs;