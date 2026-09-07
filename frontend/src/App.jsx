import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './lib/auth';
import ErrorBoundary from './components/ErrorBoundary';
import Layout from './components/Layout';
import CatalogLayout from './components/CatalogLayout';
import ForcePasswordChange from './components/ForcePasswordChange';

// Code splitting — lazy load all pages
const Login = lazy(() => import('./pages/Login'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Products = lazy(() => import('./pages/Products'));
const ProductDetail = lazy(() => import('./pages/ProductDetail'));
const Materials = lazy(() => import('./pages/Materials'));
const Machines = lazy(() => import('./pages/Machines'));
const Settings = lazy(() => import('./pages/Settings'));
const Calculator = lazy(() => import('./pages/Calculator'));
const Catalog = lazy(() => import('./pages/Catalog'));
const PublicProductDetail = lazy(() => import('./pages/PublicProductDetail'));
const Contact = lazy(() => import('./pages/Contact'));
const HowToOrder = lazy(() => import('./pages/HowToOrder'));
const CustomOrder = lazy(() => import('./pages/CustomOrder'));
const Privacy = lazy(() => import('./pages/Privacy'));
const Terms = lazy(() => import('./pages/Terms'));
const DigitalCard = lazy(() => import('./pages/DigitalCard'));
const UsersPage = lazy(() => import('./pages/Users'));
const Categories = lazy(() => import('./pages/Categories'));
const Collections = lazy(() => import('./pages/Collections'));
const Orders = lazy(() => import('./pages/Orders'));
const CustomOrders = lazy(() => import('./pages/CustomOrders'));
const Customers = lazy(() => import('./pages/Customers'));
const AuditLogs = lazy(() => import('./pages/AuditLogs'));
const BlogList = lazy(() => import('./pages/BlogList'));
const BlogPostDetail = lazy(() => import('./pages/BlogPostDetail'));
const AdminBlog = lazy(() => import('./pages/AdminBlog'));
const NotFound = lazy(() => import('./pages/NotFound'));

export function PageLoader() {
  return (
    <main className="spaghetti-loader" aria-live="polite" aria-busy="true">
      <div className="spaghetti-loader__glow" aria-hidden="true" />
      <div className="spaghetti-loader__content">
        <div className="spaghetti-loader__printer" aria-hidden="true">
          <div className="spaghetti-loader__gantry">
            <span className="spaghetti-loader__rail" />
            <span className="spaghetti-loader__nozzle" />
          </div>
          <div className="spaghetti-loader__filament" />
          <div className="spaghetti-loader__bed">
            <i /><i /><i /><i /><i />
          </div>
        </div>
        <p className="spaghetti-loader__eyebrow">SPAGHETTI PRINT</p>
        <h1>اسپاگتی پرینت</h1>
        <p className="spaghetti-loader__message">در حال آمادهسازی چاپ سه بعدی شما</p>
        <div className="spaghetti-loader__progress" aria-hidden="true"><span /></div>
      </div>
    </main>
  );
}

function ProtectedRoute({ children, requireAdmin = false }) {
  const { isAuthenticated, user, loading } = useAuth();
  if (loading) {
    return <PageLoader />;
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  if (requireAdmin && user?.role !== 'admin') {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
}

function AdminRoute({ children }) {
  return <ProtectedRoute requireAdmin>{children}</ProtectedRoute>;
}

function AppRoutes() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        {/* Public */}
                <Route path="/login" element={<Login />} />
                <Route path="/" element={<CatalogLayout><Catalog /></CatalogLayout>} />
                <Route path="/collection/:tag" element={<CatalogLayout><Catalog /></CatalogLayout>} />
                <Route path="/collections/:tag" element={<CatalogLayout><Catalog /></CatalogLayout>} />
                <Route path="/catalog/:slug" element={<CatalogLayout><PublicProductDetail /></CatalogLayout>} />
                <Route path="/contact" element={<CatalogLayout><Contact /></CatalogLayout>} />
                <Route path="/card" element={<DigitalCard />} />
                <Route path="/how-to-order" element={<CatalogLayout><HowToOrder /></CatalogLayout>} />
                <Route path="/custom-order" element={<CatalogLayout><CustomOrder /></CatalogLayout>} />
                <Route path="/privacy" element={<CatalogLayout><Privacy /></CatalogLayout>} />
                <Route path="/terms" element={<CatalogLayout><Terms /></CatalogLayout>} />
                <Route path="/blog" element={<CatalogLayout><BlogList /></CatalogLayout>} />
                <Route path="/blog/:slug" element={<CatalogLayout><BlogPostDetail /></CatalogLayout>} />

        {/* Protected admin+employee */}
        <Route path="/dashboard" element={<ProtectedRoute><Layout><Dashboard /></Layout></ProtectedRoute>} />
        <Route path="/admin/posts" element={<ProtectedRoute><Layout><AdminBlog /></Layout></ProtectedRoute>} />
        <Route path="/products" element={<ProtectedRoute><Layout><Products /></Layout></ProtectedRoute>} />
        <Route path="/products/:id" element={<ProtectedRoute><Layout><ProductDetail /></Layout></ProtectedRoute>} />
        <Route path="/products/:id/edit" element={<ProtectedRoute><Layout><ProductDetail /></Layout></ProtectedRoute>} />
        <Route path="/calculator" element={<ProtectedRoute><Layout><Calculator /></Layout></ProtectedRoute>} />
        <Route path="/categories" element={<ProtectedRoute><Layout><Categories /></Layout></ProtectedRoute>} />
        <Route path="/collections" element={<ProtectedRoute><Layout><Collections /></Layout></ProtectedRoute>} />
        <Route path="/orders" element={<ProtectedRoute><Layout><Orders /></Layout></ProtectedRoute>} />
        <Route path="/custom-orders" element={<ProtectedRoute><Layout><CustomOrders /></Layout></ProtectedRoute>} />
        <Route path="/customers" element={<ProtectedRoute><Layout><Customers /></Layout></ProtectedRoute>} />

        {/* Protected admin only */}
        <Route path="/materials" element={<AdminRoute><Layout><Materials /></Layout></AdminRoute>} />
        <Route path="/machines" element={<AdminRoute><Layout><Machines /></Layout></AdminRoute>} />
        <Route path="/settings" element={<AdminRoute><Layout><Settings /></Layout></AdminRoute>} />
        <Route path="/users" element={<AdminRoute><Layout><UsersPage /></Layout></AdminRoute>} />
        <Route path="/audit" element={<AdminRoute><Layout><AuditLogs /></Layout></AdminRoute>} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <ForcePasswordChange />
        <AppRoutes />
      </AuthProvider>
    </ErrorBoundary>
  );
}
