import axios from 'axios';
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setTokens,
} from '../utils/auth';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const NORMALIZED_API_BASE_URL = API_BASE_URL.replace(/\/+$/, '');
const API_PREFIX = NORMALIZED_API_BASE_URL.endsWith('/api')
  ? NORMALIZED_API_BASE_URL
  : `${NORMALIZED_API_BASE_URL}/api`;

const api = axios.create({
  baseURL: API_PREFIX,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as (typeof error.config & { _retry?: boolean }) | undefined;

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        const refreshToken = getRefreshToken();
        if (!refreshToken) {
          throw new Error('Missing refresh token');
        }

        const response = await axios.post(`${API_PREFIX}/token/refresh/`, {
          refresh: refreshToken,
        });

        const { access } = response.data;
        setAccessToken(access);

        originalRequest.headers = originalRequest.headers || {};
        originalRequest.headers.Authorization = `Bearer ${access}`;
        return api(originalRequest);
      } catch (refreshError) {
        clearTokens();
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export const authService = {
  register: async (username: string, email: string, password: string, password_confirm: string) => {
    const response = await api.post('/auth/register/', {
      username,
      email,
      password,
      password_confirm,
    });
    return response.data;
  },

  login: async (username: string, password: string) => {
    const response = await axios.post(`${API_PREFIX}/token/`, { username, password });
    const data = response.data || {};
    const accessToken = data.access ?? data.access_token;
    const refreshToken = data.refresh ?? data.refresh_token;

    if (!accessToken || typeof accessToken !== 'string') {
      throw new Error('Login succeeded but no access token was returned by the server.');
    }

    if (refreshToken && typeof refreshToken === 'string') {
      setTokens(accessToken, refreshToken);
    } else {
      // Some auth backends return only access token; keep user logged in without refresh flow.
      setAccessToken(accessToken);
      localStorage.removeItem('refresh_token');
    }

    return response.data;
  },

  requestPasswordReset: async (email: string) => {
    const response = await api.post('/auth/password/forgot/', { email });
    return response.data;
  },

  resetPassword: async (
    uid: string,
    token: string,
    new_password: string,
    confirm_password: string,
  ) => {
    const response = await api.post('/auth/password/reset/', {
      uid,
      token,
      new_password,
      confirm_password,
    });
    return response.data;
  },

  logout: () => {
    clearTokens();
  },
};

export const profileService = {
  get: () => api.get('/profile/me/'),
  update: (data: any) => api.put('/profile/update_me/', data),
};

export const certificationService = {
  list: () => api.get('/certifications/'),
  create: (data: any) => api.post('/certifications/', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  update: (id: number, data: any) => api.put(`/certifications/${id}/`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  delete: (id: number) => api.delete(`/certifications/${id}/`),
};

export const resumeService = {
  upload: async (file: File) => {
    const formData = new FormData();
    const fileName = file.name.toLowerCase();
    if (fileName.endsWith('.tex')) {
      formData.append('latex_file', file);
    } else {
      formData.append('original_file', file);
    }
    return api.post('/resumes/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  list: () => api.get('/resumes/'),
  delete: (id: number) => api.delete(`/resumes/${id}/`),
};

export const resumeOptimizerService = {
  generate: (data: {
    companyName: string;
    companyLocation?: string;
    jobTitle: string;
    jobDescription: string;
    requirements?: string;
    resumeId?: number;
  }) => {
    const formData = new FormData();
    formData.append('company_name', data.companyName);
    formData.append('company_location', data.companyLocation || '');
    formData.append('job_title', data.jobTitle);
    formData.append('job_description', data.jobDescription);
    formData.append('requirements', data.requirements || '');

    if (typeof data.resumeId === 'number') {
      formData.append('resume_id', String(data.resumeId));
    }

    return api.post('/resume-optimizer/generate/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

export default api;
