import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Response interceptor: handle 401 globally
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/')) {
      window.location.href = '/login';
    }
    const message = error.response?.data?.detail
      || error.response?.data?.message
      || error.message;
    console.error('[API Error]', message, error);
    return Promise.reject(error);
  }
);

// ===== Settings =====
export const getSettings = (config) => api.get('/settings', config);
export const updateSettings = (data) => api.put('/settings', data);
export const uploadBranding = (key, file) => {
  const fd = new FormData();
  fd.append('file', file);
  return api.post(`/settings/upload/${key}`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

// ===== Materials =====
export const getMaterials = (params, config) => api.get('/materials', { params, ...config });
export const getMaterialsAll = (config) => api.get('/materials/all', config);
export const createMaterial = (data) => api.post('/materials', data);
export const updateMaterial = (id, data) => api.put(`/materials/${id}`, data);
export const deleteMaterial = (id) => api.delete(`/materials/${id}`);
export const permanentDeleteMaterial = (id) => api.delete(`/materials/${id}/permanent`);
export const setDefaultMaterial = (id) => api.post(`/materials/${id}/set-default`);

// ===== Machines =====
export const getMachines = (params, config) => api.get('/machines', { params, ...config });
export const getMachinesAll = (config) => api.get('/machines/all', config);
export const createMachine = (data) => api.post('/machines', data);
export const updateMachine = (id, data) => api.put(`/machines/${id}`, data);
export const deleteMachine = (id) => api.delete(`/machines/${id}`);
export const permanentDeleteMachine = (id) => api.delete(`/machines/${id}/permanent`);
export const setDefaultMachine = (id) => api.post(`/machines/${id}/set-default`);

// ===== Products =====
export const getProducts = (params, config) => api.get('/products', { params, ...config });
export const getProductsAll = () => api.get('/products/all');
export const getProduct = (id) => api.get(`/products/${id}`);
export const createProduct = (data) => api.post('/products', data);
export const updateProduct = (id, data) => api.put(`/products/${id}`, data);
export const deleteProduct = (id) => api.delete(`/products/${id}`);
export const permanentDeleteProduct = (id) => api.delete(`/products/${id}/permanent`);
export const extractDimensions = (id) => api.post(`/products/${id}/dimensions`);

// ===== Product Images (multi) =====
export const uploadProductImages = (productId, files) => {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  return api.post(`/products/${productId}/images`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const deleteProductImage = (productId, imageId) =>
  api.delete(`/products/${productId}/images/${imageId}`);
export const setPrimaryImage = (productId, imageId) =>
  api.put(`/products/${productId}/images/${imageId}/primary`);
export const reorderProductImages = (productId, order) =>
  api.put(`/products/${productId}/images/reorder`, { order });

// ===== Product Import / Export =====
export const exportProducts = () => api.get('/products/export', { responseType: 'blob' });
export const importProducts = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/products/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

// ===== Calculator =====
export const calculate = (data, config) => api.post('/calculate', data, config);

// ===== Public Catalog & Blog (no auth) =====
const publicApi = axios.create({ baseURL: '/api/v1', withCredentials: false });
export const getPublicBrand = (config) => publicApi.get('/brand', config);
export const getCatalog = (config) => publicApi.get('/catalog', config);
export const getCatalogCategories = (config) => publicApi.get('/catalog/categories', config);
export const getCatalogCollections = (config) => publicApi.get('/catalog/collections', config);
export const getCatalogProduct = (productId, config) => publicApi.get(`/catalog/${productId}`, config);
export const getCatalogProductBySlug = (slug, config) => publicApi.get(`/catalog/by-slug/${slug}`, config);
export const recordSiteView = (path) => publicApi.post('/analytics/view', { path });
export const getBlogPosts = (config) => publicApi.get('/blog', config);
export const getBlogPostBySlug = (slug, config) => publicApi.get(`/blog/${slug}`, config);

// ===== Admin Blog CMS =====
export const getAdminBlogPosts = () => api.get('/admin/posts');
export const createBlogPost = (data) => api.post('/admin/posts', data);
export const updateBlogPost = (id, data) => api.put(`/admin/posts/${id}`, data);
export const deleteBlogPost = (id) => api.delete(`/admin/posts/${id}`);
export const uploadBlogCover = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/admin/posts/upload-cover', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

// ===== Stats =====
export const getStats = (config) => api.get('/stats', config);

// ===== Contact =====
export const getContact = (config) => publicApi.get('/contact', config);

// ===== Auth =====
export const login = (username, password) => api.post('/auth/login', { username, password });
export const logout = () => api.post('/auth/logout');

// ===== Admin Backup & Restore =====
export const exportBackup = () => api.get('/admin/backup/export', { responseType: 'blob' });
export const importBackup = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/admin/backup/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const getLocalBackups = () => api.get('/admin/backup/list');
export const uploadGDriveCreds = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/admin/backup/upload-gdrive-creds', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const pushGDriveBackup = () => api.post('/admin/backup/gdrive-upload');
export const verifyToken = () => api.get('/auth/verify');

// ===== Users (admin only) =====
export const getUsers = () => api.get('/auth/users');
export const createUser = (data) => api.post('/auth/users', data);
export const updateUser = (id, data) => api.put(`/auth/users/${id}`, data);
export const deleteUser = (id) => api.delete(`/auth/users/${id}`);
export const changePassword = (id, password) => api.put(`/auth/users/${id}/password`, { password });
export const changeMyPassword = (password) => api.post('/auth/change-my-password', { password });

// ===== Categories (admin + employee) =====
export const getCategoriesList = () => api.get('/categories');
export const getCategoriesFlat = () => api.get('/categories/all');
export const createCategory = (data) => api.post('/categories', data);
export const updateCategory = (id, data) => api.put(`/categories/${id}`, data);
export const deleteCategory = (id) => api.delete(`/categories/${id}`);

// ===== Collections =====
export const getCollectionsList = () => api.get('/collections');
export const getCollectionsFlat = () => api.get('/collections/all');
export const getCollectionsAll = () => api.get('/collections/all');
export const getCollection = (id) => api.get(`/collections/${id}`);
export const getCollectionBySlug = (slug) => api.get(`/collections/by-slug/${slug}`);
export const createCollection = (data) => api.post('/collections', data);
export const updateCollection = (id, data) => api.put(`/collections/${id}`, data);
export const deleteCollection = (id) => api.delete(`/collections/${id}`);

// ===== Orders (shop ops board B) =====
export const getOrders = (params, config) => api.get('/orders', { params, ...config });
export const getOrderStatuses = (config) => api.get('/orders/statuses', config);
export const getOrder = (id, config) => api.get(`/orders/${id}`, config);
export const createOrder = (data) => api.post('/orders', data);
export const updateOrder = (id, data) => api.put(`/orders/${id}`, data);
export const deleteOrder = (id) => api.delete(`/orders/${id}`);
export const restoreOrder = (id) => api.post(`/orders/${id}/restore`);
export const getOrderSummary = (month, config) => api.get('/orders/summary/monthly', { params: { month }, ...config });
export const exportOrdersCsv = (params, config) => api.get('/orders/export/csv', { params, responseType: 'blob', ...config });

// ===== Custom Order Requests (public submit + admin inbox) =====
export const submitCustomOrder = (data, config) => publicApi.post('/custom-orders', data, config);
export const getRequests = (status) => api.get('/admin/requests', { params: { status } });
export const updateRequest = (id, data) => api.put(`/admin/requests/${id}`, data);
export const deleteRequest = (id) => api.delete(`/admin/requests/${id}`);

// ===== Customers (CRM) =====
export const getCustomers = () => api.get('/customers');

// ===== Audit Log =====
export const getAuditLogs = (limit = 100) => api.get('/audit', { params: { limit } });

// ===== Bulk Product Actions =====
export const bulkProductAction = (data) => api.post('/products/bulk', data);

export default api;
