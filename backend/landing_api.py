"""Minimal FastAPI app for the landing-page Google sign-in flow.

Runs on port 8001 so it does not collide with the main agent backend (port 8000).
Contains only: FastAPI instance, CORSMiddleware, and the auth_google router.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth_google import router as auth_router

app = FastAPI(title="Landing API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
