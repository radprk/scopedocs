import { useState, useEffect } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Loader2, FileText, Plus, Users } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const Projects = () => {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchProjects = async () => {
    try {
      const response = await axios.get(`${API}/projects`);
      setProjects(response.data.projects || []);
    } catch (error) {
      console.error('Error fetching projects:', error);
    } finally {
      setLoading(false);
    }
  };

  const generateDoc = async (project) => {
    try {
      await axios.post(`${API}/scopedocs/generate?project_id=${project.id}&project_name=${encodeURIComponent(project.name)}`);
      alert(`Documentation generated for ${project.name}!`);
      navigate('/docs');
    } catch (error) {
      console.error('Error generating doc:', error);
      alert('Error generating documentation');
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

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
        <h1 className="text-4xl font-bold" data-testid="projects-title">Projects</h1>
        <p className="text-muted-foreground mt-2">Linear projects tracked in ScopeDocs</p>
      </div>

      {projects.length === 0 ? (
        <Card className="border-dashed" data-testid="no-projects-card">
          <CardHeader>
            <CardTitle>No Projects Found</CardTitle>
            <CardDescription>
              Generate mock data from the dashboard to see projects here
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.map((project) => (
            <Card key={project.id} className="hover:shadow-lg transition-shadow" data-testid={`project-card-${project.id}`}>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <CardTitle className="text-lg">{project.name}</CardTitle>
                    <Badge variant="secondary" className="mt-2">
                      <Users className="h-3 w-3 mr-1" />
                      {project.team}
                    </Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="text-sm text-muted-foreground">
                    {project.work_items_count} work items
                  </div>
                  <Button 
                    className="w-full" 
                    onClick={() => generateDoc(project)}
                    data-testid={`generate-doc-btn-${project.id}`}
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    Generate ScopeDoc
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};

export default Projects;